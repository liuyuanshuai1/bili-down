import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bili_text.audio import FFMPEG_ARGS, AudioConversionError, YtDlpAudioConverter, _p1_url
from bili_text.config import load_config
from bili_text.models import VideoMetadata

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def _config():
    return load_config(environ=BASE_ENV, dotenv_path=None)


def _metadata(**overrides) -> VideoMetadata:
    defaults = dict(
        uid="111",
        bv="BVtest111",
        title="标题",
        creator="博主",
        publish_time=datetime(2026, 6, 1, tzinfo=UTC),
        url="https://www.bilibili.com/video/BVtest111",
        is_multipart=False,
    )
    defaults.update(overrides)
    return VideoMetadata(**defaults)


def _ok() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


class RecordingRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str]]):
        self.responses = list(responses)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if not self.responses:
            return _ok()
        return self.responses.pop(0)


def test_p1_url_appends_page_for_multipart():
    url = _p1_url(_metadata(is_multipart=True))
    assert url.endswith("p=1")


def test_prepare_audio_runs_yt_dlp_and_ffmpeg_with_expected_args(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "BVtest111.m4a").write_bytes(b"raw")

    yt_dlp = RecordingRunner([_ok()])

    def ffmpeg_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        output = Path(command[-1])
        output.write_bytes(b"mp3")
        return _ok()

    converter = YtDlpAudioConverter(yt_dlp_runner=yt_dlp, ffmpeg_runner=ffmpeg_runner)
    output = converter.prepare_audio(_metadata(), workspace, _config())

    assert output.name == "BVtest111.mp3"
    yt_cmd = yt_dlp.commands[0]
    assert "bestaudio" in yt_cmd
    assert "--playlist-items" in yt_cmd
    assert "BVtest111" in yt_cmd[-1]


def test_prepare_audio_uses_mono_16khz_64k_ffmpeg_args(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "BVtest111.wav").write_bytes(b"raw")

    recorded: list[list[str]] = []

    def ffmpeg_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        recorded.append(command)
        Path(command[-1]).write_bytes(b"mp3")
        return _ok()

    converter = YtDlpAudioConverter(
        yt_dlp_runner=RecordingRunner([_ok()]),
        ffmpeg_runner=ffmpeg_runner,
    )
    converter.prepare_audio(_metadata(), workspace, _config())

    ffmpeg_cmd = recorded[0]
    for arg in FFMPEG_ARGS:
        assert arg in ffmpeg_cmd


def test_prepare_audio_propagates_ffmpeg_failure(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "BVtest111.wav").write_bytes(b"raw")

    converter = YtDlpAudioConverter(
        yt_dlp_runner=RecordingRunner([_ok()]),
        ffmpeg_runner=lambda _cmd: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffmpeg exploded"
        ),
    )

    with pytest.raises(AudioConversionError, match="ffmpeg exploded"):
        converter.prepare_audio(_metadata(), workspace, _config())
