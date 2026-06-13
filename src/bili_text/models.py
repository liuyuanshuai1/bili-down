"""Core domain models shared across pipeline stages.

Terminology follows ``CONTEXT.md``. These dataclasses describe the observable
state of a task; behavior for populating them lives in later pipeline slices.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class UidState(StrEnum):
    """Outcome of processing a single UID."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class VideoMetadata:
    """Identifying metadata for the latest video (P1) of a creator."""

    uid: str
    bv: str
    title: str
    creator: str
    publish_time: datetime
    url: str
    is_multipart: bool = False


@dataclass
class UidResult:
    """Result of processing one UID occurrence."""

    uid: str
    state: UidState
    metadata: VideoMetadata | None = None
    transcript: str | None = None
    single_summary: str | None = None
    artifact_path: Path | None = None
    error: str | None = None


@dataclass
class TaskResult:
    """Aggregate result for an entire task (one command invocation)."""

    timestamp: datetime
    uid_results: list[UidResult] = field(default_factory=list)
    aggregate_path: Path | None = None
    aggregate_error: str | None = None

    @property
    def counts(self) -> dict[UidState, int]:
        counter = Counter(result.state for result in self.uid_results)
        return {state: counter.get(state, 0) for state in UidState}

    @property
    def usable_summaries(self) -> list[str]:
        """Single-UP summaries available to feed the aggregate stage."""
        return [r.single_summary for r in self.uid_results if r.single_summary]
