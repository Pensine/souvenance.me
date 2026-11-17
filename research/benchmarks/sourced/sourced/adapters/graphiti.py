"""Graphiti (graphiti-core, the open-source engine behind Zep), run locally on
the same model and embedder as Pensine, so the memory system is what is
compared.

  - model: the same Claude CLI call as Pensine's `claude-cli` backend (Max
    subscription, no tools), as a Graphiti LLMClient; Graphiti's own prompts
    and its JSON schemas are sent unchanged, for its "small" calls too;
  - embedder: nomic-embed-text-v1.5 with its task prefixes, as Pensine uses it;
  - store: Kuzu, Graphiti's embedded graph database, in a fresh directory.

Graphiti itself is untouched: extraction, entity resolution, edge
invalidation, its default hybrid search (BM25 + vector, RRF; no reranker).
Each deposit is one episode, at its own reference time, described by its
kind and who wrote it to whom (the same fields Pensine receives); an
authored deposit is a message episode "Author: text", Graphiti's own
convention for who speaks.

What Graphiti records is reported as it records it: an edge's fact, its
validity (valid_at / invalid_at), the episodes it came from (provenance, no
excerpt) and its source entity (the subject). It keeps no event bounds and no
identity links between a role and a name: those are reported as missing,
never filled in.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import date, datetime, timezone

from .base import Answer, Citation, DepositView, MemoryRecord, MemorySystem

MODEL = os.environ.get("SOURCED_GRAPHITI_MODEL", "claude-sonnet-5-5")
CLAUDE_BIN = os.environ.get("PENSINE_CLAUDE_BIN", "claude")
EMBEDDER = "nomic-ai/nomic-embed-text-v1.5"
TOP_K = 10
# parallel model calls inside one episode; Kuzu takes one query at a time
CONCURRENCY = int(os.environ.get("SOURCED_GRAPHITI_CONCURRENCY", "4"))

# The reader every system shares (adapters/mem0.py ANSWER_SYSTEM).
ANSWER_SYSTEM = (
    "You answer questions about {owner}'s life using ONLY the memory context "
    "provided (JSON from a memory engine). Reply with the shortest possible answer: "
    "a few words, a name, a number or a date. Write dates as '8 May 2025'. "
    "If the context does not contain the answer, reply exactly: No information")


async def claude(system: str, prompt: str) -> str:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--model", MODEL]
    if system:
        cmd += ["--append-system-prompt", system]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {(err or out).decode()[:300]}")
    return json.loads(out.decode()).get("result", "")


def parse_json(text: str) -> dict:
    """The first JSON object in a reply (code fences and prose around it
    tolerated); a reply without one raises, so Graphiti's retry applies."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("reply is not a JSON object")
    return value


def render(d: DepositView) -> str:
    who = f" from {d.author}" if d.author else ""
    to = f" to {d.recipient}" if d.recipient else ""
    return f"{d.kind}{who}{to}"


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


class GraphitiSystem(MemorySystem):
    name = "graphiti"

    def __init__(self, owner: str = ""):
        self.owner = owner
        self.dir = ""
        self.failed = 0
        self.g = None
        self.loop = asyncio.new_event_loop()
        self.episode_deposit: dict[str, str] = {}
        self.errors: set[str] = set()
        self.searching = [False]

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def reset(self) -> None:
        os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
        os.environ["EMBEDDING_DIM"] = "768"
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.driver.kuzu_driver import KuzuDriver
        from graphiti_core.embedder.client import EmbedderClient
        from graphiti_core.llm_client.client import LLMClient
        from graphiti_core.llm_client.config import LLMConfig
        from sentence_transformers import SentenceTransformer

        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = tempfile.mkdtemp(prefix="sourced-graphiti-")
        st = SentenceTransformer(EMBEDDER, trust_remote_code=True)

        def embed(texts: list[str], prefix: str) -> list[list[float]]:
            return st.encode([prefix + t for t in texts], normalize_embeddings=True).tolist()

        searching = self.searching

        class Nomic(EmbedderClient):
            # Graphiti embeds queries and documents through the same call:
            # the query prefix while answer() searches, the document prefix
            # otherwise, as Mem0's adapter does for its search calls
            async def create(self, input_data):
                text = input_data if isinstance(input_data, str) else " ".join(map(str, input_data))
                prefix = "search_query: " if searching[0] else "search_document: "
                return embed([text], prefix)[0]

            async def create_batch(self, input_data_list):
                return embed(list(input_data_list), "search_document: ")

        class Cosine(CrossEncoderClient):
            # never called by the default search recipe; present because the
            # constructor would otherwise build an OpenAI reranker
            async def rank(self, query, passages):
                q = embed([query], "search_query: ")[0]
                ps = embed(passages, "search_document: ")
                scored = [(p, sum(a * b for a, b in zip(q, v))) for p, v in zip(passages, ps)]
                return sorted(scored, key=lambda x: -x[1])

        class ClaudeCLI(LLMClient):
            def _get_provider_type(self) -> str:
                return "claude-cli"

            async def _generate_response(self, messages, response_model=None,
                                         max_tokens=None, model_size=None, *, model=None):
                system = "\n\n".join(m.content for m in messages if m.role == "system")
                prompt = "\n\n".join(m.content for m in messages if m.role != "system")
                prompt += "\n\nReply with one JSON object only, no code fence."
                return parse_json(await claude(system, prompt))

        driver = KuzuDriver(db=f"{self.dir}/graph.kuzu")
        self.g = Graphiti(graph_driver=driver,
                          llm_client=ClaudeCLI(LLMConfig(model=MODEL, small_model=MODEL)),
                          embedder=Nomic(), cross_encoder=Cosine(),
                          max_coroutines=CONCURRENCY)
        self._run(self.g.build_indices_and_constraints())
        # KuzuDriver.build_indices_and_constraints is a no-op in this release,
        # so the full-text indices its own search needs are never created:
        # create them as graphiti's Kuzu graph operations would
        from graphiti_core.driver.driver import GraphProvider
        from graphiti_core.graph_queries import get_fulltext_indices
        for q in get_fulltext_indices(GraphProvider.KUZU):
            self._run(driver.execute_query(q))
        # the provider's default group (a named group breaks the Kuzu driver
        # in this release: KuzuDriver has no `_database`)
        from graphiti_core.helpers import get_default_group_id
        self.group = get_default_group_id(driver.provider)
        self.episode_deposit = {}

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        from graphiti_core.nodes import EpisodeType

        for d in deposits:
            if d.text is None:
                raise NotImplementedError("Track R (raw media) not wired for Graphiti")
            at = datetime.fromisoformat(d.created_at).replace(tzinfo=timezone.utc)
            # Graphiti's own convention for who speaks: a message episode
            # written "Speaker: text"; unauthored deposits (documents) as text
            body, kind = ((f"{d.author}: {d.text}", EpisodeType.message) if d.author
                          else (d.text, EpisodeType.text))
            try:
                r = self._run(self.g.add_episode(
                    name=d.id, episode_body=body, source_description=render(d),
                    reference_time=at, source=kind, group_id=None))
                self.episode_deposit[r.episode.uuid] = d.id
            except Exception as exc:  # one failed episode loses one deposit, as for Mem0
                self.failed += 1
                self.errors.add(type(exc).__name__)

    def memories(self) -> list[MemoryRecord]:
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode

        from graphiti_core.errors import GroupsEdgesNotFoundError
        try:
            edges = self._run(EntityEdge.get_by_group_ids(self.g.driver, [self.group]))
        except GroupsEdgesNotFoundError:
            return []
        uuids = list({e.source_node_uuid for e in edges})
        nodes = self._run(EntityNode.get_by_uuids(self.g.driver, uuids)) if uuids else []
        names = {n.uuid: n.name for n in nodes}
        out = []
        for e in edges:
            deps = [self.episode_deposit[u] for u in e.episodes if u in self.episode_deposit]
            out.append(MemoryRecord(
                e.uuid, e.fact,
                valid_from=_iso(e.valid_at), valid_to=_iso(e.invalid_at),
                current=e.invalid_at is None and e.expired_at is None,
                citations=[Citation(x) for x in deps],
                subject=names.get(e.source_node_uuid, "")))
        return out

    def answer(self, question: str, asked_at: date) -> Answer:
        self.searching[0] = True
        try:
            hits = self._run(self.g.search(question, group_ids=[self.group], num_results=TOP_K))
        finally:
            self.searching[0] = False
        context = json.dumps([{"fact": h.fact, "valid_at": _iso(h.valid_at),
                               "invalid_at": _iso(h.invalid_at)} for h in hits],
                             ensure_ascii=False)
        text = self._run(claude(ANSWER_SYSTEM.format(owner=self.owner),
                                f"Today is {asked_at.isoformat()}.\nMemory context:\n{context}"
                                f"\n\nQuestion: {question}"))
        return Answer(text.strip())

    def describe(self) -> dict:
        from importlib.metadata import version
        return {"name": self.name, "graphiti-core": version("graphiti-core"),
                "kuzu": version("kuzu"), "llm": f"claude-cli:{MODEL}", "embedder": EMBEDDER,
                "store": "kuzu local", "search": "default hybrid RRF, no reranker",
                "top_k": TOP_K, "concurrency": CONCURRENCY, "failed_episodes": self.failed,
                "episode_errors": sorted(self.errors)}
