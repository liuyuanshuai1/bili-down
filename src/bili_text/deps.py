"""Pipeline dependency wiring for CLI and integration tests."""

from __future__ import annotations

from .audio import YtDlpAudioConverter
from .bilibili import YtDlpBilibiliExtractor
from .fakes import DeterministicFakes
from .orchestrator import PipelineDeps
from .storage import MinioObjectStorage
from .summarization import DashScopeSummarizer
from .transcription import DashScopeTranscriber


def build_pipeline_deps() -> PipelineDeps:
    """Build the default production pipeline."""
    fakes = DeterministicFakes()
    return PipelineDeps(
        bilibili=YtDlpBilibiliExtractor(),
        audio=YtDlpAudioConverter(),
        storage=MinioObjectStorage(),
        transcriber=DashScopeTranscriber(),
        summarizer=DashScopeSummarizer(),
        renderer=fakes.renderer,
    )
