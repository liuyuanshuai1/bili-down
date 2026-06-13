"""MinIO object storage for temporary audio uploads."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from .config import AppConfig, redact_secrets
from .models import VideoMetadata

PRESIGNED_URL_TTL = timedelta(hours=24)
LIFECYCLE_RULE_ID = "bili-text-one-day-expiry"
OBJECT_KEY_PREFIX = "bili-skill"

WarningReporter = Callable[[str], None]


class ObjectStorageError(Exception):
    """Raised when MinIO upload or presigning fails."""


def _default_warn(message: str) -> None:
    import sys

    print(f"Warning: {message}", file=sys.stderr)


def build_object_key(uid: str, bv: str, *, at: datetime | None = None) -> str:
    """Return ``bili-skill/{UID}/{BV}/{timestamp}-{UUID}.mp3``."""
    moment = at or datetime.now(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%S%z")
    return f"{OBJECT_KEY_PREFIX}/{uid}/{bv}/{stamp}-{uuid.uuid4()}.mp3"


def _minio_client(config: AppConfig) -> Minio:
    parsed = urlparse(config.minio_endpoint)
    if not parsed.hostname:
        raise ObjectStorageError("MINIO_ENDPOINT must include a host")
    host = parsed.netloc
    secure = parsed.scheme == "https"
    return Minio(
        host,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=secure,
    )


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def _apply_lifecycle(client: Minio, bucket: str, warn: WarningReporter) -> None:
    lifecycle = LifecycleConfig(
        [
            Rule(
                ENABLED,
                rule_id=LIFECYCLE_RULE_ID,
                rule_filter=Filter(prefix=""),
                expiration=Expiration(days=1),
            ),
        ],
    )
    try:
        client.set_bucket_lifecycle(bucket, lifecycle)
    except S3Error as exc:
        warn(
            "Could not configure one-day lifecycle on bucket "
            f"{bucket}: {exc.code or exc.message}"
        )


class MinioClientProtocol(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> None: ...

    def set_bucket_lifecycle(self, bucket_name: str, config: LifecycleConfig) -> None: ...

    def fput_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        content_type: str = "application/octet-stream",
    ) -> object: ...

    def presigned_get_object(
        self,
        bucket_name: str,
        object_name: str,
        expires: timedelta = timedelta(days=7),
    ) -> str: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...


@dataclass
class MinioObjectStorage:
    """Uploads audio to MinIO and returns a presigned HTTPS URL."""

    client_factory: Callable[[AppConfig], MinioClientProtocol] | None = None
    on_warning: WarningReporter = _default_warn
    _bucket_ready: set[str] = field(default_factory=set)

    def _client(self, config: AppConfig) -> MinioClientProtocol:
        if self.client_factory is not None:
            return self.client_factory(config)
        return _minio_client(config)

    def _prepare_bucket(self, client: MinioClientProtocol, config: AppConfig) -> None:
        bucket = config.minio_bucket
        if bucket in self._bucket_ready:
            return
        _ensure_bucket(client, bucket)
        _apply_lifecycle(client, bucket, self.on_warning)
        self._bucket_ready.add(bucket)

    def upload(self, audio_path: Path, metadata: VideoMetadata, config: AppConfig) -> str:
        if not audio_path.exists():
            raise ObjectStorageError(f"audio file not found: {audio_path.name}")

        object_key = build_object_key(metadata.uid, metadata.bv)
        bucket = config.minio_bucket

        try:
            client = self._client(config)
            self._prepare_bucket(client, config)
            client.fput_object(
                bucket,
                object_key,
                str(audio_path),
                content_type="audio/mpeg",
            )
            url = client.presigned_get_object(bucket, object_key, expires=PRESIGNED_URL_TTL)
        except S3Error as exc:
            detail = exc.message or exc.code or "MinIO upload failed"
            raise ObjectStorageError(redact_secrets(detail, config)) from exc
        except OSError as exc:
            raise ObjectStorageError(redact_secrets(str(exc), config)) from exc

        if not url.startswith("https://"):
            raise ObjectStorageError("presigned URL must use HTTPS")
        return url
