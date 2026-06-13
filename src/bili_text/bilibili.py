"""Bilibili metadata extraction via the ``yt-dlp`` CLI."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import AppConfig, redact_secrets
from .models import VideoMetadata

BV_PATTERN = re.compile(r"BV[\w]+")
SPACE_VIDEO_URL = "https://space.bilibili.com/{uid}/video"


class BilibiliExtractionError(Exception):
    """Raised when ``yt-dlp`` cannot extract metadata for a UID."""


@dataclass(frozen=True)
class _FlatEntry:
    webpage_url: str
    publish_time: datetime


def _space_url(uid: str) -> str:
    return SPACE_VIDEO_URL.format(uid=uid)


def _extract_bv(entry: dict) -> str:
    bvid = entry.get("bvid")
    if isinstance(bvid, str) and bvid:
        return bvid if bvid.startswith("BV") else f"BV{bvid}"

    vid = entry.get("id")
    if isinstance(vid, str) and vid.startswith("BV"):
        return vid

    for key in ("webpage_url", "url"):
        value = entry.get(key)
        if isinstance(value, str):
            match = BV_PATTERN.search(value)
            if match:
                return match.group(0)

    raise BilibiliExtractionError("could not determine BV number from yt-dlp output")


def _parse_publish_time(entry: dict) -> datetime:
    timestamp = entry.get("timestamp")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=UTC)

    upload_date = entry.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8:
        return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)

    raise BilibiliExtractionError("missing publication time in yt-dlp output")


def _parse_flat_entry(entry: dict) -> _FlatEntry:
    url = entry.get("webpage_url") or entry.get("url")
    if not isinstance(url, str) or not url:
        raise BilibiliExtractionError("missing video URL in yt-dlp playlist entry")
    return _FlatEntry(webpage_url=url, publish_time=_parse_publish_time(entry))


def _select_latest(entries: Sequence[_FlatEntry]) -> _FlatEntry:
    if not entries:
        raise BilibiliExtractionError("no videos found for this UID")
    return max(entries, key=lambda item: item.publish_time)


def _is_multipart(info: dict) -> bool:
    playlist_count = info.get("playlist_count")
    if isinstance(playlist_count, int) and playlist_count > 1:
        return True
    nested = info.get("entries")
    return isinstance(nested, list) and len(nested) > 1


def _build_yt_dlp_command(config: AppConfig, *args: str) -> list[str]:
    command = ["yt-dlp"]
    if config.bili_cookie:
        command.extend(["--add-header", f"Cookie:{config.bili_cookie}"])
    command.extend(args)
    return command


def _run_yt_dlp(
    config: AppConfig,
    *args: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> str:
    command = _build_yt_dlp_command(config, *args)
    run = runner or (
        lambda cmd: subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    )
    try:
        completed = run(command)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise BilibiliExtractionError(redact_secrets(detail or "yt-dlp failed", config)) from exc
    except OSError as exc:
        raise BilibiliExtractionError(redact_secrets(str(exc), config)) from exc

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise BilibiliExtractionError("yt-dlp returned no output")
    return stdout


def _parse_flat_playlist(stdout: str) -> list[_FlatEntry]:
    payload = json.loads(stdout)
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        if payload.get("id"):
            raw_entries = [payload]
        else:
            raw_entries = []
    return [_parse_flat_entry(entry) for entry in raw_entries if isinstance(entry, dict)]


def _metadata_from_info(uid: str, info: dict) -> VideoMetadata:
    bv = _extract_bv(info)
    title = info.get("title")
    creator = info.get("uploader") or info.get("channel") or info.get("uploader_id")
    url = info.get("webpage_url") or info.get("url")
    if not isinstance(title, str) or not title:
        raise BilibiliExtractionError("missing video title in yt-dlp output")
    if not isinstance(creator, str) or not creator:
        raise BilibiliExtractionError("missing creator name in yt-dlp output")
    if not isinstance(url, str) or not url:
        url = f"https://www.bilibili.com/video/{bv}"

    return VideoMetadata(
        uid=uid,
        bv=bv,
        title=title,
        creator=creator,
        publish_time=_parse_publish_time(info),
        url=url,
        is_multipart=_is_multipart(info),
    )


@dataclass
class YtDlpBilibiliExtractor:
    """Selects the latest published video (P1 metadata) for a UID via ``yt-dlp``."""

    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None

    def fetch_latest(self, uid: str, config: AppConfig) -> VideoMetadata:
        playlist_stdout = _run_yt_dlp(
            config,
            "-J",
            "--flat-playlist",
            "--no-warnings",
            _space_url(uid),
            runner=self.runner,
        )
        latest = _select_latest(_parse_flat_playlist(playlist_stdout))

        detail_stdout = _run_yt_dlp(
            config,
            "-J",
            "--no-warnings",
            "--playlist-items",
            "1",
            latest.webpage_url,
            runner=self.runner,
        )
        info = json.loads(detail_stdout)
        return _metadata_from_info(uid, info)
