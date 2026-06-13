"""Application configuration loading and validation.

Configuration comes from process environment variables, optionally seeded by a
`.env` file. Process environment variables take precedence over `.env`.
Secrets must never appear in error messages or logs; use :func:`redact_secrets`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

DEFAULT_ASR_MODEL = "qwen3-asr-flash"
DEFAULT_SUMMARY_MODEL = "deepseek-v4-flash"

REQUIRED_VARS: tuple[str, ...] = (
    "DASHSCOPE_API_KEY",
    "MINIO_ENDPOINT",
    "MINIO_BUCKET",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
)

# Ports commonly used by the MinIO management console rather than the S3 API.
_CONSOLE_PORTS = {9001}


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    dashscope_api_key: str
    minio_endpoint: str
    minio_bucket: str
    minio_access_key: str
    minio_secret_key: str
    bili_cookie: str | None
    asr_model: str
    summary_model: str
    output_dir: Path

    def secret_values(self) -> tuple[str, ...]:
        """Return the non-empty secret strings that must be redacted."""
        candidates = (
            self.dashscope_api_key,
            self.minio_access_key,
            self.minio_secret_key,
            self.bili_cookie,
        )
        return tuple(value for value in candidates if value)


def _clean(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


def _merge_env(
    environ: Mapping[str, str], dotenv_path: str | os.PathLike[str] | None
) -> dict[str, str]:
    merged: dict[str, str] = {}
    if dotenv_path is not None and Path(dotenv_path).exists():
        for key, value in dotenv_values(dotenv_path).items():
            if value is not None:
                merged[key] = value
    # Process environment takes precedence over the .env file.
    merged.update(environ)
    return merged


def validate_endpoint(endpoint: str) -> None:
    """Validate that ``endpoint`` is a public HTTPS S3 API URL (not a console)."""
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise ConfigError(
            "MINIO_ENDPOINT must be an HTTPS URL "
            f"(got scheme '{parsed.scheme or '(none)'}')"
        )
    if not parsed.netloc:
        raise ConfigError("MINIO_ENDPOINT must include a host")
    if parsed.port in _CONSOLE_PORTS or "console" in (parsed.hostname or ""):
        raise ConfigError(
            "MINIO_ENDPOINT looks like a management console URL; "
            "use the S3 API endpoint instead"
        )


def load_config(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> AppConfig:
    """Load and validate configuration.

    Args:
        environ: Process environment mapping. Defaults to ``os.environ``.
        dotenv_path: Optional path to a ``.env`` file to seed defaults.
        output_dir: Optional output root from the CLI; defaults to CWD.
    """
    environ = os.environ if environ is None else environ
    merged = _merge_env(environ, dotenv_path)

    missing = [name for name in REQUIRED_VARS if not _clean(merged.get(name))]
    if missing:
        raise ConfigError("Missing required configuration: " + ", ".join(missing))

    endpoint = _clean(merged["MINIO_ENDPOINT"])
    assert endpoint is not None  # guaranteed by the missing-vars check above
    validate_endpoint(endpoint)

    cookie = _clean(merged.get("BILI_COOKIE")) or None
    asr_model = _clean(merged.get("ASR_MODEL")) or DEFAULT_ASR_MODEL
    summary_model = _clean(merged.get("SUMMARY_MODEL")) or DEFAULT_SUMMARY_MODEL
    resolved_output = Path(output_dir) if output_dir is not None else Path.cwd()

    return AppConfig(
        dashscope_api_key=_clean(merged["DASHSCOPE_API_KEY"]) or "",
        minio_endpoint=endpoint,
        minio_bucket=_clean(merged["MINIO_BUCKET"]) or "",
        minio_access_key=_clean(merged["MINIO_ACCESS_KEY"]) or "",
        minio_secret_key=_clean(merged["MINIO_SECRET_KEY"]) or "",
        bili_cookie=cookie,
        asr_model=asr_model,
        summary_model=summary_model,
        output_dir=resolved_output,
    )


def redact_secrets(message: str, secrets: AppConfig | Iterable[str]) -> str:
    """Replace any secret substrings in ``message`` with ``***``."""
    values: Iterable[str]
    if isinstance(secrets, AppConfig):
        values = secrets.secret_values()
    else:
        values = secrets
    redacted = message
    for value in sorted((v for v in values if v), key=len, reverse=True):
        redacted = redacted.replace(value, "***")
    return redacted
