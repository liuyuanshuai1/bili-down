"""Explicit interfaces (Protocols) for each pipeline stage.

Concrete implementations and fakes are provided by later slices. Keeping these
boundaries explicit lets the orchestration layer be tested with deterministic
fakes instead of real network/media dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .config import AppConfig
from .models import VideoMetadata


@runtime_checkable
class BilibiliExtractor(Protocol):
    """Selects the latest video (P1) for a UID and exposes its metadata."""

    def fetch_latest(self, uid: str, config: AppConfig) -> VideoMetadata: ...


@runtime_checkable
class AudioConverter(Protocol):
    """Downloads P1 audio and normalizes it to mono 16 kHz 64 kbps MP3."""

    def prepare_audio(
        self, metadata: VideoMetadata, workspace: Path, config: AppConfig
    ) -> Path: ...


@runtime_checkable
class ObjectStorage(Protocol):
    """Uploads audio to MinIO and returns a presigned HTTPS URL."""

    def upload(self, audio_path: Path, metadata: VideoMetadata, config: AppConfig) -> str: ...


@runtime_checkable
class Transcriber(Protocol):
    """Transcribes audio referenced by a presigned URL via DashScope ASR."""

    def transcribe(self, audio_url: str, config: AppConfig) -> str: ...


@runtime_checkable
class Summarizer(Protocol):
    """Generates single-UP and aggregate summaries via DashScope chat models."""

    def summarize_single(
        self, transcript: str, metadata: VideoMetadata, config: AppConfig
    ) -> str: ...

    def summarize_aggregate(self, summaries: list[str], config: AppConfig) -> str: ...


@runtime_checkable
class MarkdownRenderer(Protocol):
    """Renders UID and aggregate Markdown artifacts."""

    def render_uid(self, metadata: VideoMetadata, summary: str | None, transcript: str) -> str: ...

    def render_aggregate(self, report: str) -> str: ...
