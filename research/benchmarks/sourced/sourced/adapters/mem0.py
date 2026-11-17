"""Mem0 (open-source library, mem0ai), run locally on the same model and
embedder as Pensine, so the memory system is what is compared.

  - model: the same Claude CLI call as Pensine's `claude-cli` backend (Max
    subscription, no tools), put in place of Mem0's OpenAI client;
  - embedder: nomic-embed-text-v1.5 with its task prefixes, as Pensine uses it;
  - store: Mem0's own local Qdrant and history database, in a fresh directory.

Mem0 itself is untouched: its prompts, its extraction and update decisions,
its retrieval. Each deposit is one `add`, written as a dated user message with
who wrote it to whom (the same fields Pensine receives); the deposit id rides
in Mem0's metadata, which is all the provenance Mem0 keeps (no excerpt).

What Mem0 does not record is reported as such, never filled in: no subject
(attribution not measurable), no event date, no identity links. Mem0 OSS
grounds relative dates on the machine's clock ("timestamp" is platform-only):
a known temporal error, reported, not corrected.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import date

from .base import Answer, Citation, DepositView, MemoryRecord, MemorySystem

USER = "owner"
MODEL = os.environ.get("SOURCED_MEM0_MODEL", "claude-sonnet-5-5")
CLAUDE_BIN = os.environ.get("PENSINE_CLAUDE_BIN", "claude")
EMBEDDER = "nomic-ai/nomic-embed-text-v1.5"
TOP_K = 10

# The reader every system shares (sourced/adapters/pensine.py ANSWER_SYSTEM),
# minus the Pensine-specific interval field.
ANSWER_SYSTEM = (
    "You answer questions about {owner}'s life using ONLY the memory context "
    "provided (JSON from a memory engine). Reply with the shortest possible answer: "
    "a few words, a name, a number or a date. Write dates as '8 May 2025'. "
    "If the context does not contain the answer, reply exactly: No information")


def claude(messages: list[dict], json_mode: bool = False) -> str:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    prompt = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    if json_mode:
        prompt += "\n\nReply with one JSON object only, no code fence."
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--model", MODEL]
    if system:
        cmd += ["--append-system-prompt", system]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {(proc.stderr or proc.stdout)[:300]}")
    return json.loads(proc.stdout).get("result", "")


def render(d: DepositView, owner: str) -> str:
    who = f"from {d.author}" if d.author else ""
    to = f" to {d.recipient}" if d.recipient else ""
    return f"[{d.created_at} · {d.kind} {who}{to} · {owner}'s record]\n{d.text}"


class Mem0System(MemorySystem):
    name = "mem0"

    def __init__(self, owner: str = ""):
        self.owner = owner
        self.dir = ""
        self.failed = 0
        self.m = None

    def reset(self) -> None:
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        from mem0 import Memory

        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = tempfile.mkdtemp(prefix="sourced-mem0-")
        self.m = Memory.from_config({
            "llm": {"provider": "openai", "config": {"api_key": "unused", "model": MODEL}},
            "embedder": {"provider": "huggingface",
                         "config": {"model": EMBEDDER, "embedding_dims": 768,
                                    "model_kwargs": {"trust_remote_code": True}}},
            "vector_store": {"provider": "qdrant",
                             "config": {"path": f"{self.dir}/qdrant", "on_disk": True,
                                        "embedding_model_dims": 768,
                                        "collection_name": "sourced"}},
            "history_db_path": f"{self.dir}/history.db",
        })
        self.m.llm.generate_response = (
            lambda messages, response_format=None, **_: claude(messages, bool(response_format)))
        st = self.m.embedding_model.model
        prefix = {"search": "search_query: "}

        def embed(text, memory_action=None):
            return st.encode(prefix.get(memory_action, "search_document: ") + text,
                             normalize_embeddings=True).tolist()

        def embed_batch(texts, memory_action="add"):
            return [embed(t, memory_action) for t in texts]

        self.m.embedding_model.embed = embed
        self.m.embedding_model.embed_batch = embed_batch

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        for d in deposits:
            if d.text is None:
                raise NotImplementedError("Track R (raw media) not wired for Mem0")
            try:
                self.m.add([{"role": "user", "content": render(d, self.owner)}], user_id=USER,
                           metadata={"deposit_id": d.id, "deposited_at": d.created_at})
            except Exception:  # one failed call loses one deposit, as a failed batch would
                self.failed += 1

    def memories(self) -> list[MemoryRecord]:
        rows = self.m.get_all(filters={"user_id": USER}, top_k=100000).get("results", [])
        out = []
        for r in rows:
            dep = (r.get("metadata") or {}).get("deposit_id")
            out.append(MemoryRecord(str(r["id"]), r.get("memory", ""),
                                    citations=[Citation(dep)] if dep else []))
        return out

    def answer(self, question: str, asked_at: date) -> Answer:
        hits = self.m.search(question, filters={"user_id": USER}, top_k=TOP_K).get("results", [])
        context = json.dumps([{"memory": h.get("memory"),
                               "recorded": (h.get("metadata") or {}).get("deposited_at")}
                              for h in hits], ensure_ascii=False)
        text = claude([{"role": "system", "content": ANSWER_SYSTEM.format(owner=self.owner)},
                       {"role": "user", "content": f"Today is {asked_at.isoformat()}.\n"
                                                   f"Memory context:\n{context}\n\n"
                                                   f"Question: {question}"}])
        return Answer(text.strip())

    def describe(self) -> dict:
        from importlib.metadata import version
        return {"name": self.name, "mem0ai": version("mem0ai"), "llm": f"claude-cli:{MODEL}",
                "embedder": EMBEDDER, "store": "qdrant local", "top_k": TOP_K,
                "failed_adds": self.failed}
