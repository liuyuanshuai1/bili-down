"""Task orchestration: sequential UID processing and aggregate generation."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig, redact_secrets
from .interfaces import (
    AudioConverter,
    BilibiliExtractor,
    MarkdownRenderer,
    ObjectStorage,
    Summarizer,
    Transcriber,
)
from .markdown import MarkdownRendererImpl
from .models import TaskResult, UidResult, UidState

StatusReporter = Callable[[str], None]


@dataclass(frozen=True)
class PipelineDeps:
    bilibili: BilibiliExtractor
    audio: AudioConverter
    storage: ObjectStorage
    transcriber: Transcriber
    summarizer: Summarizer
    renderer: MarkdownRenderer


def format_task_timestamp(value: datetime) -> str:
    """Compact, filesystem-safe task timestamp (timezone-aware)."""
    return value.strftime("%Y%m%dT%H%M%S%z")


def uid_artifact_path(output_dir: Path, uid: str, task_timestamp: datetime, bv: str) -> Path:
    stamp = format_task_timestamp(task_timestamp)
    return output_dir / uid / f"{stamp}-{bv}.md"


def aggregate_artifact_path(output_dir: Path, task_timestamp: datetime) -> Path:
    stamp = format_task_timestamp(task_timestamp)
    return output_dir / f"{stamp}-summary.md"


def _report_status(reporter: StatusReporter | None, message: str) -> None:
    if reporter is not None:
        reporter(message)


def _save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def process_uid(
    uid: str,
    config: AppConfig,
    deps: PipelineDeps,
    *,
    task_timestamp: datetime,
    reporter: StatusReporter | None = None,
) -> UidResult:
    """Run the full pipeline for one UID occurrence."""
    workspace = Path(tempfile.mkdtemp(prefix="bili-text-"))

    try:
        _report_status(reporter, f"UID {uid}: extracting latest video")
        metadata = deps.bilibili.fetch_latest(uid, config)

        _report_status(reporter, f"UID {uid}: preparing audio")
        audio_path = deps.audio.prepare_audio(metadata, workspace, config)

        _report_status(reporter, f"UID {uid}: uploading audio")
        audio_url = deps.storage.upload(audio_path, metadata, config)

        _report_status(reporter, f"UID {uid}: transcribing")
        transcript = deps.transcriber.transcribe(audio_url, config)

        summary: str | None = None
        summary_error: str | None = None
        try:
            _report_status(reporter, f"UID {uid}: summarizing")
            summary = deps.summarizer.summarize_single(transcript, metadata, config)
        except Exception as exc:  # noqa: BLE001 — per-UID summary failure becomes partial
            summary_error = redact_secrets(str(exc), config)

        if summary is not None:
            state = UidState.SUCCESS
        else:
            state = UidState.PARTIAL

        render_summary = summary
        if isinstance(deps.renderer, MarkdownRendererImpl):
            markdown = deps.renderer.render_uid(
                metadata,
                render_summary,
                transcript,
                summary_error=summary_error,
            )
        else:
            markdown = deps.renderer.render_uid(metadata, render_summary, transcript)

        artifact = uid_artifact_path(config.output_dir, uid, task_timestamp, metadata.bv)
        _save_text(artifact, markdown)

        return UidResult(
            uid=uid,
            state=state,
            metadata=metadata,
            transcript=transcript,
            single_summary=summary,
            artifact_path=artifact,
            error=summary_error,
        )
    except Exception as exc:  # noqa: BLE001 — isolate per-UID failures
        error = redact_secrets(str(exc), config)
        _report_status(reporter, f"UID {uid}: failed — {error}")
        return UidResult(uid=uid, state=UidState.FAILED, error=error)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_task(
    uids: list[str],
    config: AppConfig,
    deps: PipelineDeps,
    *,
    task_timestamp: datetime | None = None,
    reporter: StatusReporter | None = None,
) -> TaskResult:
    """Process all UIDs sequentially and generate the aggregate artifact when possible."""
    if task_timestamp is None:
        task_timestamp = datetime.now(ZoneInfo("Asia/Shanghai"))

    task = TaskResult(timestamp=task_timestamp)
    covered: list[tuple[str, str, str]] = []

    for uid in uids:
        uid_result = process_uid(
            uid,
            config,
            deps,
            task_timestamp=task_timestamp,
            reporter=reporter,
        )
        task.uid_results.append(uid_result)
        _report_status(reporter, f"UID {uid}: {uid_result.state.value}")

        if uid_result.metadata is not None:
            covered.append(
                (uid_result.metadata.uid, uid_result.metadata.bv, uid_result.metadata.title)
            )

    summaries = task.usable_summaries
    if not summaries:
        _report_status(reporter, "Aggregate: skipped (no usable single-UP summaries)")
        return task

    try:
        _report_status(reporter, "Aggregate: generating task-wide summary")
        report = deps.summarizer.summarize_aggregate(summaries, config)
        if isinstance(deps.renderer, MarkdownRendererImpl):
            markdown = deps.renderer.render_aggregate(
                report, covered=covered, task_timestamp=task_timestamp
            )
        else:
            markdown = deps.renderer.render_aggregate(report)
        aggregate_path = aggregate_artifact_path(config.output_dir, task_timestamp)
        _save_text(aggregate_path, markdown)
        task.aggregate_path = aggregate_path
        _report_status(reporter, "Aggregate: success")
    except Exception as exc:  # noqa: BLE001
        task.aggregate_error = redact_secrets(str(exc), config)
        _report_status(reporter, f"Aggregate: failed — {task.aggregate_error}")

    counts = task.counts
    _report_status(
        reporter,
        "Task complete: "
        f"{counts[UidState.SUCCESS]} success, "
        f"{counts[UidState.PARTIAL]} partial, "
        f"{counts[UidState.FAILED]} failed",
    )
    return task


def task_exit_code(task: TaskResult) -> int:
    """Map a :class:`TaskResult` to a process exit code."""
    counts = task.counts
    any_uid_ok = counts[UidState.SUCCESS] + counts[UidState.PARTIAL] > 0
    if counts[UidState.FAILED] == len(task.uid_results) and task.uid_results:
        return 4
    has_partial_or_failed = counts[UidState.PARTIAL] > 0 or counts[UidState.FAILED] > 0
    if task.aggregate_error is not None or has_partial_or_failed:
        return 3 if any_uid_ok else 4
    return 0
