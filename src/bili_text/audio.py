"""P1 audio download and ffmpeg normalization."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .bilibili import _build_yt_dlp_command
from .config import AppConfig, redact_secrets
from .models import VideoMetadata

FFMPEG_ARGS = ("-ac", "1", "-ar", "16000", "-b:a", "64k")


class AudioConversionError(Exception):
    """Raised when audio download or conversion fails."""


def _p1_url(metadata: VideoMetadata) -> str:
    url = metadata.url
    if metadata.is_multipart and "p=" not in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}p=1"
    return url


def _run_checked(
    command: list[str],
    *,
    config: AppConfig,
    label: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    try:
        completed = runner(command)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise AudioConversionError(
            redact_secrets(detail or f"{label} failed", config)
        ) from exc
    except OSError as exc:
        raise AudioConversionError(redact_secrets(str(exc), config)) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise AudioConversionError(redact_secrets(detail or f"{label} failed", config))


def _find_downloaded_source(workspace: Path, bv: str) -> Path:
    matches = sorted(workspace.glob(f"{bv}.*"))
    matches = [path for path in matches if path.suffix.lower() != ".mp3"]
    if not matches:
        raise AudioConversionError(f"yt-dlp did not produce a source file for {bv}")
    return matches[0]


@dataclass
class YtDlpAudioConverter:
    """Downloads P1 best audio via ``yt-dlp`` and normalizes with ``ffmpeg``."""

    yt_dlp_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    ffmpeg_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None

    def prepare_audio(
        self, metadata: VideoMetadata, workspace: Path, config: AppConfig
    ) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        source_stem = workspace / metadata.bv
        output_path = workspace / f"{metadata.bv}.mp3"

        yt_dlp_runner = self.yt_dlp_runner or (
            lambda cmd: subprocess.run(cmd, check=False, capture_output=True, text=True)
        )
        ffmpeg_runner = self.ffmpeg_runner or (
            lambda cmd: subprocess.run(cmd, check=False, capture_output=True, text=True)
        )

        download_cmd = _build_yt_dlp_command(
            config,
            "-f",
            "bestaudio",
            "--no-warnings",
            "--playlist-items",
            "1",
            "-o",
            f"{source_stem}.%(ext)s",
            _p1_url(metadata),
        )
        _run_checked(
            download_cmd,
            config=config,
            label="yt-dlp audio download",
            runner=yt_dlp_runner,
        )

        source_path = _find_downloaded_source(workspace, metadata.bv)
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            *FFMPEG_ARGS,
            str(output_path),
        ]
        _run_checked(
            ffmpeg_cmd,
            config=config,
            label="ffmpeg",
            runner=ffmpeg_runner,
        )

        if not output_path.exists():
            raise AudioConversionError("ffmpeg did not produce the expected MP3 output")
        return output_path
