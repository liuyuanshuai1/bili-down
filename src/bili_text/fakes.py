"""Deterministic pipeline fakes for orchestration tests and the walking skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import AppConfig
from .markdown import MarkdownRendererImpl
from .models import VideoMetadata


@dataclass
class FakeFailure:
    """Stage at which a UID should fail when using :class:`DeterministicFakes`."""

    uid: str
    stage: str  # extract | audio | upload | transcribe | summarize


@dataclass
class DeterministicFakes:
    """In-memory implementations of all pipeline stage interfaces."""

    failures: list[FakeFailure] = field(default_factory=list)
    renderer: MarkdownRendererImpl = field(default_factory=MarkdownRendererImpl)
    stage_log: list[tuple[str, str]] = field(default_factory=list)
    upload_requests: list[tuple[str, str]] = field(default_factory=list)
    asr_requests: list[str] = field(default_factory=list)
    aggregate_inputs: list[list[str]] = field(default_factory=list)

    def _record_stage(self, stage: str, uid: str) -> None:
        self.stage_log.append((stage, uid))

    def _fail_stage(self, uid: str, stage: str) -> None:
        if any(f.uid == uid and f.stage == stage for f in self.failures):
            raise RuntimeError(f"fake {stage} failure for uid {uid}")

    def fetch_latest(self, uid: str, config: AppConfig) -> VideoMetadata:
        self._record_stage("extract", uid)
        self._fail_stage(uid, "extract")
        return VideoMetadata(
            uid=uid,
            bv=f"BVfake{uid}",
            title=f"Fake title for {uid}",
            creator=f"Creator {uid}",
            publish_time=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            url=f"https://www.bilibili.com/video/BVfake{uid}",
            is_multipart=uid.endswith("mp"),
        )

    def prepare_audio(
        self, metadata: VideoMetadata, workspace: Path, config: AppConfig
    ) -> Path:
        self._record_stage("audio", metadata.uid)
        self._fail_stage(metadata.uid, "audio")
        workspace.mkdir(parents=True, exist_ok=True)
        audio_path = workspace / f"{metadata.bv}.mp3"
        audio_path.write_bytes(b"fake-audio")
        return audio_path

    def upload(self, audio_path: Path, metadata: VideoMetadata, config: AppConfig) -> str:
        self._record_stage("upload", metadata.uid)
        self.upload_requests.append((metadata.uid, audio_path.name))
        self._fail_stage(metadata.uid, "upload")
        return f"https://minio.example.com/{metadata.uid}/{audio_path.name}"

    def transcribe(self, audio_url: str, config: AppConfig) -> str:
        # UID is embedded in the fake URL path segment.
        uid = audio_url.rsplit("/", 1)[0].rsplit("/", 1)[-1]
        self._record_stage("transcribe", uid)
        self.asr_requests.append(audio_url)
        self._fail_stage(uid, "transcribe")
        return f"转写正文（UID {uid}）。"

    def summarize_single(
        self, transcript: str, metadata: VideoMetadata, config: AppConfig
    ) -> str:
        self._record_stage("summarize", metadata.uid)
        self._fail_stage(metadata.uid, "summarize")
        snippet = transcript[:20]
        return (
            f"### 主要主题\n\n针对 {metadata.creator} 的财经观点。\n\n"
            f"### 宏观经济与行业背景\n\n宏观背景摘要。\n\n"
            f"### 核心判断\n\n{snippet}…\n\n"
            f"### 影响链条\n\n利率→估值→板块。\n\n"
            f"### UP 主建议\n\n建议观望。\n\n"
            f"### 风险\n\n政策不确定性。"
        )

    def summarize_aggregate(self, summaries: list[str], config: AppConfig) -> str:
        self.aggregate_inputs.append(list(summaries))
        joined = "\n\n".join(summaries)
        return (
            "### 主要主题\n\n跨 UP 宏观主题。\n\n"
            "### 共识\n\n多位 UP 主观点汇总。\n\n"
            "### 分歧与理由\n\n存在分歧。\n\n"
            "### 竞争判断的成立条件\n\n取决于通胀路径。\n\n"
            "### 跨主题联系\n\n利率与板块联动。\n\n"
            "### 综合影响\n\n流动性主导。\n\n"
            "### 研究与行动建议\n\n跟踪数据。\n\n"
            f"### 风险\n\n下行风险。\n\n{joined}"
        )
