"""The adapter contract: what a memory system must expose to be measured.

A system sees deposits day by day, in chronological order, exactly as a
person would drop them: never the truth, the fact labels, the spans or the
traps (`DepositView` carries none of them). After each simulated day it may
consolidate (`end_of_day`). At checkpoints the harness asks for its full
memory store (`memories`), then at the end it asks the questions.

Systems that cannot export their store (consumer chat memories) implement
`memories()` by raising `NotImplementedError`: their write-time metrics are
then reported as "not measurable", never silently dropped or imputed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class DepositView:
    id: str
    kind: str            # note | message | message_in | voice | voice_in | photo | document
    created_at: str      # ISO datetime, local time of the life
    author: str          # display name of who produced it ("" for documents)
    recipient: str       # display name, "" if none
    text: str | None     # Track T: transcript / EXIF summary / PDF text. None on Track R
    path: str | None     # absolute path of the media file (both tracks when rendered)


@dataclass
class Citation:
    deposit_id: str
    excerpt: str = ""


@dataclass
class MemoryRecord:
    id: str
    content: str
    valid_from: str | None = None    # ISO date or datetime, if the system dates memories
    valid_to: str | None = None
    current: bool | None = None      # does the system present it as true now? None = unknown
    confidence: float | None = None  # enables the recall/invention curve
    citations: list[Citation] = field(default_factory=list)


@dataclass
class Answer:
    text: str
    abstained: bool | None = None    # explicit flag if the system has one
    citations: list[Citation] = field(default_factory=list)


class MemorySystem(ABC):
    name = "abstract"
    tracks: tuple[str, ...] = ("T",)

    def reset(self) -> None:
        """Start from an empty memory. Called once before a run."""

    @abstractmethod
    def ingest(self, deposits: list[DepositView], day: date) -> None:
        """Receive one day of deposits (possibly empty)."""

    def end_of_day(self, day: date) -> None:
        """Hook for nightly consolidation. Default: nothing."""

    @abstractmethod
    def memories(self) -> list[MemoryRecord]:
        """The full memory store as of now."""

    @abstractmethod
    def answer(self, question: str, asked_at: date) -> Answer:
        """Answer from memory only. Abstaining is a legitimate answer."""

    def describe(self) -> dict:
        """Versions, models, settings: copied verbatim into the run file."""
        return {"name": self.name}
