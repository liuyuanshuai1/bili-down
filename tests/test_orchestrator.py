from datetime import UTC, datetime
from pathlib import Path

from bili_text.config import load_config
from bili_text.fakes import DeterministicFakes, FakeFailure
from bili_text.models import UidState
from bili_text.orchestrator import (
    PipelineDeps,
    aggregate_artifact_path,
    format_task_timestamp,
    process_uid,
    run_task,
    task_exit_code,
    uid_artifact_path,
)

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def _deps(**fake_kwargs) -> PipelineDeps:
    fakes = DeterministicFakes(**fake_kwargs)
    return PipelineDeps(
        bilibili=fakes,
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=fakes,
        renderer=fakes.renderer,
    )


def _config(tmp_path: Path):
    return load_config(environ=BASE_ENV, dotenv_path=None, output_dir=tmp_path)


def test_output_paths_use_timestamp_bv_and_uid_directory(tmp_path: Path):
    task_ts = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    uid_path = uid_artifact_path(tmp_path, "999", task_ts, "BVfake999")
    agg_path = aggregate_artifact_path(tmp_path, task_ts)

    assert uid_path.parent == tmp_path / "999"
    assert uid_path.name.startswith(format_task_timestamp(task_ts))
    assert uid_path.name.endswith("-BVfake999.md")
    assert "宏观" not in uid_path.name
    assert agg_path.name == f"{format_task_timestamp(task_ts)}-summary.md"


def test_single_uid_success_writes_uid_and_aggregate_markdown(tmp_path: Path):
    messages: list[str] = []
    config = _config(tmp_path)
    task_ts = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)

    task = run_task(["111"], config, _deps(), task_timestamp=task_ts, reporter=messages.append)

    uid_file = tmp_path / "111" / f"{format_task_timestamp(task_ts)}-BVfake111.md"
    agg_file = tmp_path / f"{format_task_timestamp(task_ts)}-summary.md"

    assert task.uid_results[0].state is UidState.SUCCESS
    assert uid_file.exists()
    assert agg_file.exists()
    assert task.aggregate_path == agg_file
    assert "完整转写" not in "\n".join(messages)
    assert any("Task complete: 1 success" in m for m in messages)


def test_multi_uid_sequential_processing_and_shared_timestamp(tmp_path: Path):
    config = _config(tmp_path)
    task_ts = datetime(2026, 6, 12, 11, 0, tzinfo=UTC)

    task = run_task(["111", "222"], config, _deps(), task_timestamp=task_ts)

    stamp = format_task_timestamp(task_ts)
    assert (tmp_path / "111" / f"{stamp}-BVfake111.md").exists()
    assert (tmp_path / "222" / f"{stamp}-BVfake222.md").exists()
    assert (tmp_path / f"{stamp}-summary.md").exists()
    assert len(task.uid_results) == 2
    assert all(r.state is UidState.SUCCESS for r in task.uid_results)


def test_failure_isolation_continues_later_uids(tmp_path: Path):
    config = _config(tmp_path)
    deps = _deps(failures=[FakeFailure(uid="bad", stage="extract")])

    task = run_task(["good", "bad", "also-good"], config, deps)

    states = [r.state for r in task.uid_results]
    assert states == [UidState.SUCCESS, UidState.FAILED, UidState.SUCCESS]
    assert (tmp_path / "good").exists()
    assert (tmp_path / "also-good").exists()
    assert not (tmp_path / "bad").exists()


def test_partial_state_when_summary_fails(tmp_path: Path):
    config = _config(tmp_path)
    deps = _deps(failures=[FakeFailure(uid="111", stage="summarize")])

    result = process_uid(
        "111",
        config,
        deps,
        task_timestamp=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
    )

    assert result.state is UidState.PARTIAL
    assert result.transcript is not None
    assert result.single_summary is None
    assert result.artifact_path is not None
    content = result.artifact_path.read_text(encoding="utf-8")
    assert "汇总失败" in content
    assert "完整转写" in content


def test_failed_uid_produces_no_artifact(tmp_path: Path):
    config = _config(tmp_path)
    deps = _deps(failures=[FakeFailure(uid="111", stage="transcribe")])

    result = process_uid(
        "111",
        config,
        deps,
        task_timestamp=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
    )

    assert result.state is UidState.FAILED
    assert result.artifact_path is None
    assert not (tmp_path / "111").exists()


def test_aggregate_skipped_when_all_uids_fail(tmp_path: Path):
    config = _config(tmp_path)
    deps = _deps(failures=[FakeFailure(uid="111", stage="extract")])

    task = run_task(["111"], config, deps)

    assert task.aggregate_path is None
    assert task_exit_code(task) == 4


def test_aggregate_failure_preserves_uid_files(tmp_path: Path):
    from dataclasses import dataclass

    from bili_text.fakes import DeterministicFakes
    from bili_text.summarization import SummarizationError

    config = _config(tmp_path)
    fakes = DeterministicFakes()

    @dataclass
    class FailingAggregateSummarizer:
        backend: DeterministicFakes

        def summarize_single(self, transcript, metadata, config):
            return self.backend.summarize_single(transcript, metadata, config)

        def summarize_aggregate(self, summaries, config):
            raise SummarizationError("aggregate generation failed")

    deps = PipelineDeps(
        bilibili=fakes,
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=FailingAggregateSummarizer(fakes),
        renderer=fakes.renderer,
    )
    task_ts = datetime(2026, 6, 12, 13, 0, tzinfo=UTC)

    task = run_task(["111"], config, deps, task_timestamp=task_ts)

    uid_file = tmp_path / "111" / f"{format_task_timestamp(task_ts)}-BVfake111.md"
    assert uid_file.exists()
    assert task.aggregate_path is None
    assert task.aggregate_error is not None
    assert task_exit_code(task) == 3


def test_task_exit_code_partial_on_mixed_results(tmp_path: Path):
    config = _config(tmp_path)
    deps = _deps(failures=[FakeFailure(uid="bad", stage="extract")])

    task = run_task(["ok", "bad"], config, deps)

    assert task_exit_code(task) == 3
