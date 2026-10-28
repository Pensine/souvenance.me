"""Adapters for other memory systems: documented skeletons, NOT executed.

None of these has been run. Running them calls paid or third-party services
and is deferred until the protocol is frozen and its judge validated (SPEC
§8). Each class states which API it would use and which metrics it can be
measured on; `memories()` raises NotImplementedError where a system has no
export, and the harness then reports write metrics as "not measurable".

Before any run: pin the SDK version and the service date in `describe()`,
and read the provider's terms on automated evaluation.
"""

from __future__ import annotations

from datetime import date

from .base import Answer, DepositView, MemoryRecord, MemorySystem

_NOT_RUN = "skeleton only: this adapter has never been executed (see SPEC §8)"


class _Skeleton(MemorySystem):
    api = ""
    write_metrics = True

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        raise NotImplementedError(_NOT_RUN)

    def memories(self) -> list[MemoryRecord]:
        raise NotImplementedError(_NOT_RUN)

    def answer(self, question: str, asked_at: date) -> Answer:
        raise NotImplementedError(_NOT_RUN)

    def describe(self) -> dict:
        return {"name": self.name, "api": self.api, "status": "not run"}


class Mem0System(_Skeleton):
    """Mem0 (open-source library or hosted platform).
    ingest: `Memory.add(messages, user_id=…, metadata={"deposit_id", "created_at"})`,
            one call per deposit, text rendering only (Track T).
    memories: `Memory.get_all(user_id=…)` — content + metadata; no excerpt
            citation, so excerpt support is 0 by definition, not N/A.
    answer: `Memory.search(question)` then a fixed open-weights reader (same
            reader for every system, so retrieval is what is compared).
    Timestamps: pass created_at in metadata; Mem0's own clock is the run date
    (a known source of temporal error, to be reported, not corrected)."""
    name, api = "mem0", "mem0ai (pin version)"


class ZepSystem(_Skeleton):
    """Zep / Graphiti (temporal knowledge graph).
    ingest: `graph.add(user_id, type="text", data=…)` or episodes with
            `reference_time = created_at` (Graphiti keeps event time natively).
    memories: facts/edges with `valid_at` / `invalid_at` → MemoryRecord with
            valid_from/valid_to and current = invalid_at is None.
    answer: graph search + the shared reader."""
    name, api = "zep", "zep-cloud or graphiti-core (pin version)"


class SupermemorySystem(_Skeleton):
    """Supermemory. ingest: add documents (text, and files for Track R if the
    API accepts audio/images/PDF); memories: list memories/documents;
    answer: search + the shared reader."""
    name, api = "supermemory", "supermemory API (pin version)"


class MemobaseSystem(_Skeleton):
    """Memobase (user profile memory). ingest: insert chat-style blobs per
    deposit with the created_at timestamp; memories: user profile + event
    timeline; answer: context API + the shared reader."""
    name, api = "memobase", "memobase SDK (pin version)"


class ChatGPTMemorySystem(_Skeleton):
    """ChatGPT consumer memory. No programmatic write or export API is used:
    deposits would be pasted into fresh chats in order, the saved memories
    read from the settings page (manual transcription), questions asked in a
    fresh chat. Write metrics only as far as the visible memory list allows;
    excerpt support = 0 (no citations). Manual protocol, documented run log."""
    name, api = "chatgpt-memory", "consumer app, manual protocol"
    write_metrics = False


class ClaudeMemorySystem(_Skeleton):
    """Claude consumer memory, same manual protocol as ChatGPT: deposits in
    order, memory summary read from settings, questions in a fresh chat."""
    name, api = "claude-memory", "consumer app, manual protocol"
    write_metrics = False


REGISTRY = {c.name: c for c in (Mem0System, ZepSystem, SupermemorySystem, MemobaseSystem,
                                ChatGPTMemorySystem, ClaudeMemorySystem)}
