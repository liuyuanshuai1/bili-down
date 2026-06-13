from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from minio.lifecycleconfig import LifecycleConfig

from bili_text.config import load_config
from bili_text.models import VideoMetadata
from bili_text.storage import (
    MinioObjectStorage,
    ObjectStorageError,
    build_object_key,
)

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
        uid="12345",
        bv="BVtest123",
        title="标题",
        creator="博主",
        publish_time=datetime(2026, 6, 1, tzinfo=UTC),
        url="https://www.bilibili.com/video/BVtest123",
    )
    defaults.update(overrides)
    return VideoMetadata(**defaults)


class FakeMinioClient:
    def __init__(
        self,
        *,
        lifecycle_error: Exception | None = None,
        upload_error: Exception | None = None,
    ):
        self.lifecycle_error = lifecycle_error
        self.upload_error = upload_error
        self.bucket_exists_calls = 0
        self.make_bucket_calls = 0
        self.lifecycle_configs: list[LifecycleConfig] = []
        self.uploads: list[tuple[str, str, str]] = []
        self.presigned_calls: list[tuple[str, str, timedelta]] = []
        self.remove_calls: list[tuple[str, str]] = []
        self._existing_buckets: set[str] = set()

    def bucket_exists(self, bucket_name: str) -> bool:
        self.bucket_exists_calls += 1
        return bucket_name in self._existing_buckets

    def make_bucket(self, bucket_name: str) -> None:
        self.make_bucket_calls += 1
        self._existing_buckets.add(bucket_name)

    def set_bucket_lifecycle(self, bucket_name: str, config: LifecycleConfig) -> None:
        if self.lifecycle_error is not None:
            raise self.lifecycle_error
        self.lifecycle_configs.append(config)

    def fput_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        content_type: str = "application/octet-stream",
    ) -> object:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((bucket_name, object_name, content_type))
        return None

    def presigned_get_object(
        self,
        bucket_name: str,
        object_name: str,
        expires: timedelta = timedelta(days=7),
    ) -> str:
        self.presigned_calls.append((bucket_name, object_name, expires))
        return f"https://minio.example.com/{bucket_name}/{object_name}?sig=test"

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))


def test_build_object_key_shape():
    key = build_object_key("999", "BVabc", at=datetime(2026, 6, 12, 8, 30, tzinfo=UTC))

    assert key.startswith("bili-skill/999/BVabc/20260612T083000+0000-")
    assert key.endswith(".mp3")


def test_upload_creates_bucket_applies_lifecycle_and_presigns(tmp_path: Path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"mp3")
    fake = FakeMinioClient()
    warnings: list[str] = []
    storage = MinioObjectStorage(
        client_factory=lambda _cfg: fake,
        on_warning=warnings.append,
    )

    url = storage.upload(audio, _metadata(), _config())

    assert fake.make_bucket_calls == 1
    assert len(fake.lifecycle_configs) == 1
    assert fake.uploads[0][0] == "bili-text-audio"
    assert fake.uploads[0][1].startswith("bili-skill/12345/BVtest123/")
    assert fake.uploads[0][2] == "audio/mpeg"
    assert url.startswith("https://")
    assert fake.remove_calls == []


def test_upload_skips_bucket_setup_when_already_prepared(tmp_path: Path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"mp3")
    fake = FakeMinioClient()
    fake._existing_buckets.add("bili-text-audio")
    storage = MinioObjectStorage(client_factory=lambda _cfg: fake)

    storage.upload(audio, _metadata(), _config())
    storage.upload(audio, _metadata(uid="222"), _config())

    assert fake.make_bucket_calls == 0
    assert len(fake.lifecycle_configs) == 1
    assert len(fake.uploads) == 2


def test_lifecycle_failure_emits_warning_but_upload_succeeds(tmp_path: Path):
    from minio.error import S3Error

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"mp3")
    fake = FakeMinioClient(
        lifecycle_error=S3Error("lifecycle denied", "AccessDenied", "403", "", "", ""),
    )
    warnings: list[str] = []
    storage = MinioObjectStorage(
        client_factory=lambda _cfg: fake,
        on_warning=warnings.append,
    )

    url = storage.upload(audio, _metadata(), _config())

    assert url.startswith("https://")
    assert any("lifecycle" in message.lower() for message in warnings)


def test_upload_failure_is_redacted(tmp_path: Path):
    from minio.error import S3Error

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"mp3")
    fake = FakeMinioClient(
        upload_error=S3Error("bad key secret-secret", "InvalidAccessKeyId", "403", "", "", "")
    )
    storage = MinioObjectStorage(client_factory=lambda _cfg: fake)

    with pytest.raises(ObjectStorageError) as excinfo:
        storage.upload(audio, _metadata(), _config())

    assert "secret-secret" not in str(excinfo.value)


def test_missing_audio_file_raises(tmp_path: Path):
    storage = MinioObjectStorage(client_factory=lambda _cfg: FakeMinioClient())

    with pytest.raises(ObjectStorageError, match="audio file not found"):
        storage.upload(tmp_path / "missing.mp3", _metadata(), _config())
