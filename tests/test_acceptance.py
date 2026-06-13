"""End-to-end acceptance tests at the CLI orchestration seam.

All external dependencies (yt-dlp, ffmpeg, MinIO, DashScope) are replaced by
deterministic fakes. These tests assert externally visible behavior: exit codes,
terminal status events, generated Markdown, pipeline stage ordering, and secret
redaction — without network access or large media fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bili_text.cli import EXIT_ALL_FAILED, EXIT_OK, main
from bili_text.config import load_config
from bili_text.fakes import DeterministicFakes, FakeFailure
from bili_text.models import UidState
from bili_text.orchestrator import PipelineDeps, process_uid, run_task

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
    "BILI_COOKIE": "SESSDATA=super-secret-cookie",
}

STAGES = ("extract", "audio", "upload", "transcribe", "summarize")


def _config(tmp_path: Path, **overrides):
    return load_config(environ={**BASE_ENV, **overrides}, dotenv_path=None, output_dir=tmp_path)


def _deps(**fake_kwargs) -> tuple[PipelineDeps, DeterministicFakes]:
    fakes = DeterministicFakes(**fake_kwargs)
    deps = PipelineDeps(
        bilibili=fakes,
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=fakes,
        renderer=fakes.renderer,
    )
    return deps, fakes


def _cli_env(**overrides) -> dict[str, str]:
    return {**BASE_ENV, **overrides}


def test_single_uid_cli_acceptance(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    deps, fakes = _deps()
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", lambda: deps)

    exit_code = main(["111mp", "--output-dir", str(tmp_path)], environ=_cli_env())
    captured = capsys.readouterr()

    uid_files = list((tmp_path / "111mp").glob("*.md"))
    agg_files = list(tmp_path.glob("*-summary.md"))

    assert exit_code == EXIT_OK
    assert len(uid_files) == 1
    assert len(agg_files) == 1
    assert "Prerequisites OK" in captured.out
    assert "Task complete: 1 success, 0 partial, 0 failed" in captured.out
    assert "完整转写" not in captured.out

    uid_body = uid_files[0].read_text(encoding="utf-8")
    assert "## 源信息" in uid_body
    assert "仅处理 P1" in uid_body
    assert "## 单 UP 汇总" in uid_body
    assert "### 主要主题" in uid_body
    assert "## 完整转写" in uid_body

    agg_body = agg_files[0].read_text(encoding="utf-8")
    assert "## 综合分析" in agg_body
    assert "### 共识" in agg_body

    assert [stage for stage, uid in fakes.stage_log if uid == "111mp"] == list(STAGES)
    assert fakes.upload_requests == [("111mp", "BVfake111mp.mp3")]
    assert fakes.asr_requests == ["https://minio.example.com/111mp/BVfake111mp.mp3"]
    assert len(fakes.aggregate_inputs) == 1
    assert "主要主题" in fakes.aggregate_inputs[0][0]
    assert "## 完整转写" not in fakes.aggregate_inputs[0][0]


def test_multi_uid_cli_acceptance(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    deps, fakes = _deps()
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", lambda: deps)

    exit_code = main(["111", "222", "111", "--output-dir", str(tmp_path)], environ=_cli_env())
    captured = capsys.readouterr()

    uid111_files = sorted((tmp_path / "111").glob("*.md"))
    uid222_files = sorted((tmp_path / "222").glob("*.md"))

    assert exit_code == EXIT_OK
    assert len(uid111_files) == 1
    assert len(uid222_files) == 1
    shared_stamp = uid111_files[0].name.split("-", 1)[0]
    assert uid222_files[0].name.startswith(shared_stamp)
    assert (tmp_path / f"{shared_stamp}-summary.md").exists()
    assert captured.out.index("UID 111:") < captured.out.index("UID 222:")
    assert "Task complete: 3 success, 0 partial, 0 failed" in captured.out
    assert len(fakes.aggregate_inputs[0]) == 3
    assert len([uid for _stage, uid in fakes.stage_log if uid == "111"]) == 10


@pytest.mark.parametrize("failed_stage", STAGES)
def test_failure_isolation_does_not_block_later_uids(tmp_path, failed_stage):
    config = _config(tmp_path)
    deps, _fakes = _deps(failures=[FakeFailure(uid="bad", stage=failed_stage)])

    task = run_task(["first", "bad", "third"], config, deps)

    assert [r.uid for r in task.uid_results] == ["first", "bad", "third"]
    assert task.uid_results[0].state is UidState.SUCCESS
    assert task.uid_results[2].state is UidState.SUCCESS
    if failed_stage == "summarize":
        assert task.uid_results[1].state is UidState.PARTIAL
    else:
        assert task.uid_results[1].state is UidState.FAILED
    assert (tmp_path / "first").exists()
    assert (tmp_path / "third").exists()
    assert not (tmp_path / "bad").exists() or failed_stage == "summarize"


def test_partial_uid_summary_not_included_in_aggregate_input(tmp_path):
    config = _config(tmp_path)
    deps, fakes = _deps(failures=[FakeFailure(uid="partial", stage="summarize")])

    task = run_task(["ok", "partial"], config, deps)

    assert task.uid_results[1].state is UidState.PARTIAL
    assert len(fakes.aggregate_inputs) == 1
    assert len(fakes.aggregate_inputs[0]) == 1
    assert "Creator ok" in fakes.aggregate_inputs[0][0]


def test_workspace_cleaned_after_uid_processing(tmp_path, monkeypatch):
    config = _config(tmp_path)
    deps, _fakes = _deps()
    workspace = tmp_path / "uid-workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "bili_text.orchestrator.tempfile.mkdtemp",
        lambda prefix: str(workspace),
    )

    process_uid(
        "111",
        config,
        deps,
        task_timestamp=datetime(2026, 6, 12, 17, 0, tzinfo=UTC),
    )

    assert not workspace.exists()


def test_cli_redacts_cookie_on_uid_failure(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    fakes = DeterministicFakes()

    class FailingExtractor:
        def fetch_latest(self, _uid, _config):
            raise RuntimeError("extract failed with SESSDATA=super-secret-cookie")

    deps = PipelineDeps(
        bilibili=FailingExtractor(),
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=fakes,
        renderer=fakes.renderer,
    )
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", lambda: deps)

    exit_code = main(["111", "--output-dir", str(tmp_path)], environ=_cli_env())
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert exit_code == EXIT_ALL_FAILED
    assert "super-secret-cookie" not in combined
    assert "SESSDATA" not in combined or "***" in combined


def test_cli_redacts_all_secrets_on_startup_and_runtime_errors(capsys, monkeypatch, tmp_path):
    env = _cli_env()
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda _name: None)

    startup_code = main(["111", "--output-dir", str(tmp_path)], environ=env)
    startup_output = capsys.readouterr()
    startup_combined = startup_output.out + startup_output.err

    assert startup_code != EXIT_OK
    for secret in ("sk-dashscope-secret", "access-secret", "secret-secret", "super-secret-cookie"):
        assert secret not in startup_combined

    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    deps, _fakes = _deps(failures=[FakeFailure(uid="111", stage="upload")])
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", lambda: deps)

    runtime_code = main(["111", "--output-dir", str(tmp_path)], environ=env)
    runtime_output = capsys.readouterr()
    runtime_combined = runtime_output.out + runtime_output.err

    assert runtime_code == EXIT_ALL_FAILED
    for secret in ("sk-dashscope-secret", "access-secret", "secret-secret"):
        assert secret not in runtime_combined
