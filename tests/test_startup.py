from pathlib import Path

from bili_text.config import load_config
from bili_text.startup import (
    check_executable,
    check_output_dir,
    check_python_version,
    failed_checks,
    run_startup_checks,
)

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def test_check_executable_missing():
    result = check_executable("yt-dlp", finder=lambda _name: None)
    assert result.ok is False
    assert "yt-dlp" in result.name


def test_check_executable_present():
    result = check_executable("ffmpeg", finder=lambda _name: "/usr/bin/ffmpeg")
    assert result.ok is True


def test_check_python_version_below_minimum():
    result = check_python_version(minimum=(3, 12), current=(3, 10, 0))
    assert result.ok is False


def test_check_python_version_ok():
    result = check_python_version(minimum=(3, 12), current=(3, 12, 13))
    assert result.ok is True


def test_check_output_dir_creates_and_writable(tmp_path: Path):
    target = tmp_path / "nested" / "out"
    result = check_output_dir(target)
    assert result.ok is True
    assert target.exists()


def test_run_startup_checks_reports_missing_executable(tmp_path: Path):
    config = load_config(environ=BASE_ENV, dotenv_path=None, output_dir=tmp_path)

    def which(name: str):
        return None if name == "ffmpeg" else f"/usr/bin/{name}"

    results = run_startup_checks(
        config, which=which, current_version=(3, 12, 13)
    )
    failures = failed_checks(results)

    assert any("ffmpeg" in r.name for r in failures)
    assert all("yt-dlp" not in r.name for r in failures)
