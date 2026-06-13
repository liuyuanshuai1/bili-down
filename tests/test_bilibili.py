import json
import subprocess

import pytest

from bili_text.bilibili import (
    BilibiliExtractionError,
    YtDlpBilibiliExtractor,
    _parse_flat_playlist,
    _select_latest,
)
from bili_text.config import load_config

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def _config(cookie: str | None = None):
    env = dict(BASE_ENV)
    if cookie is not None:
        env["BILI_COOKIE"] = cookie
    return load_config(environ=env, dotenv_path=None)


def _completed(stdout: str, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _flat_playlist_payload(entries: list[dict]) -> str:
    return json.dumps({"entries": entries})


def _detail_payload(**overrides) -> str:
    defaults = {
        "id": "BVlatest111",
        "bvid": "BVlatest111",
        "title": "宏观展望",
        "uploader": "财经博主",
        "webpage_url": "https://www.bilibili.com/video/BVlatest111",
        "upload_date": "20260610",
        "playlist_count": 1,
    }
    defaults.update(overrides)
    return json.dumps(defaults)


class RecordingRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str]]):
        self.responses = list(responses)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if not self.responses:
            raise AssertionError("no more mocked yt-dlp responses")
        response = self.responses.pop(0)
        if response.returncode != 0:
            raise subprocess.CalledProcessError(
                response.returncode, command, output=response.stdout, stderr=response.stderr
            )
        return response


def test_select_latest_by_publication_time_not_list_order():
    entries = _parse_flat_playlist(
        _flat_playlist_payload(
            [
                {
                    "webpage_url": "https://www.bilibili.com/video/BVold",
                    "upload_date": "20260101",
                },
                {
                    "webpage_url": "https://www.bilibili.com/video/BVnew",
                    "upload_date": "20260610",
                },
                {
                    "webpage_url": "https://www.bilibili.com/video/BVmid",
                    "upload_date": "20260315",
                },
            ]
        )
    )

    latest = _select_latest(entries)

    assert latest.webpage_url.endswith("BVnew")


def test_fetch_latest_uses_playlist_items_one_for_p1_metadata():
    runner = RecordingRunner(
        [
            _completed(
                _flat_playlist_payload(
                    [
                        {
                            "webpage_url": "https://www.bilibili.com/video/BVlatest111",
                            "upload_date": "20260610",
                        }
                    ]
                )
            ),
            _completed(_detail_payload(playlist_count=3, entries=[{}, {}, {}])),
        ]
    )
    extractor = YtDlpBilibiliExtractor(runner=runner)
    config = _config()

    metadata = extractor.fetch_latest("12345", config)

    assert metadata.bv == "BVlatest111"
    assert metadata.uid == "12345"
    assert metadata.creator == "财经博主"
    assert metadata.is_multipart is True
    assert metadata.url == "https://www.bilibili.com/video/BVlatest111"
    detail_cmd = runner.commands[1]
    assert "--playlist-items" in detail_cmd
    assert detail_cmd[detail_cmd.index("--playlist-items") + 1] == "1"


def test_fetch_latest_without_cookie_uses_anonymous_yt_dlp():
    runner = RecordingRunner(
        [
            _completed(
                _flat_playlist_payload(
                    [
                        {
                            "webpage_url": "https://www.bilibili.com/video/BV111",
                            "upload_date": "20260601",
                        }
                    ]
                )
            ),
            _completed(_detail_payload()),
        ]
    )
    extractor = YtDlpBilibiliExtractor(runner=runner)

    extractor.fetch_latest("111", _config(cookie=None))

    assert all("--add-header" not in cmd for cmd in runner.commands)


def test_fetch_latest_with_cookie_adds_header_and_redacts_errors():
    secret = "SESSDATA=super-secret-cookie-value"
    runner = RecordingRunner(
        [
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=f"request failed with cookie {secret}",
            )
        ]
    )
    extractor = YtDlpBilibiliExtractor(runner=runner)

    with pytest.raises(BilibiliExtractionError) as excinfo:
        extractor.fetch_latest("111", _config(cookie=secret))

    assert secret not in str(excinfo.value)
    assert "Cookie:" in runner.commands[0][runner.commands[0].index("--add-header") + 1]


def test_invalid_uid_surfaces_as_extraction_failure():
    runner = RecordingRunner(
        [
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="ERROR: Unsupported URL",
            )
        ]
    )
    extractor = YtDlpBilibiliExtractor(runner=runner)

    with pytest.raises(BilibiliExtractionError):
        extractor.fetch_latest("not-a-real-uid", _config())


def test_empty_playlist_raises_without_fallback():
    runner = RecordingRunner([_completed(_flat_playlist_payload([]))])
    extractor = YtDlpBilibiliExtractor(runner=runner)

    with pytest.raises(BilibiliExtractionError, match="no videos found"):
        extractor.fetch_latest("111", _config())

    assert len(runner.commands) == 1
