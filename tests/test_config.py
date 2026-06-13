from pathlib import Path

import pytest

from bili_text.config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_SUMMARY_MODEL,
    AppConfig,
    ConfigError,
    load_config,
    redact_secrets,
)

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def test_loads_from_dotenv_file(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(f"{k}={v}" for k, v in BASE_ENV.items()) + "\n",
        encoding="utf-8",
    )

    config = load_config(environ={}, dotenv_path=dotenv)

    assert isinstance(config, AppConfig)
    assert config.dashscope_api_key == "sk-dashscope-secret"
    assert config.minio_bucket == "bili-text-audio"


def test_process_env_overrides_dotenv(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("MINIO_BUCKET=from-file\n", encoding="utf-8")
    environ = {**BASE_ENV, "MINIO_BUCKET": "from-process-env"}

    config = load_config(environ=environ, dotenv_path=dotenv)

    assert config.minio_bucket == "from-process-env"


def test_missing_required_lists_all_missing():
    with pytest.raises(ConfigError) as excinfo:
        load_config(environ={"MINIO_BUCKET": "only-bucket"}, dotenv_path=None)

    message = str(excinfo.value)
    assert "DASHSCOPE_API_KEY" in message
    assert "MINIO_ENDPOINT" in message
    assert "MINIO_ACCESS_KEY" in message
    assert "MINIO_SECRET_KEY" in message


def test_non_https_endpoint_rejected():
    environ = {**BASE_ENV, "MINIO_ENDPOINT": "http://minio.example.com"}
    with pytest.raises(ConfigError):
        load_config(environ=environ, dotenv_path=None)


def test_console_endpoint_rejected():
    environ = {**BASE_ENV, "MINIO_ENDPOINT": "https://minio.example.com:9001"}
    with pytest.raises(ConfigError):
        load_config(environ=environ, dotenv_path=None)


def test_model_defaults_and_overrides():
    default_cfg = load_config(environ=BASE_ENV, dotenv_path=None)
    assert default_cfg.asr_model == DEFAULT_ASR_MODEL
    assert default_cfg.summary_model == DEFAULT_SUMMARY_MODEL

    overridden = load_config(
        environ={**BASE_ENV, "ASR_MODEL": "custom-asr", "SUMMARY_MODEL": "custom-sum"},
        dotenv_path=None,
    )
    assert overridden.asr_model == "custom-asr"
    assert overridden.summary_model == "custom-sum"


def test_cookie_optional_defaults_to_none():
    config = load_config(environ=BASE_ENV, dotenv_path=None)
    assert config.bili_cookie is None

    with_cookie = load_config(
        environ={**BASE_ENV, "BILI_COOKIE": "SESSDATA=abc"}, dotenv_path=None
    )
    assert with_cookie.bili_cookie == "SESSDATA=abc"


def test_output_dir_defaults_and_override(tmp_path: Path):
    default_cfg = load_config(environ=BASE_ENV, dotenv_path=None)
    assert default_cfg.output_dir == Path.cwd()

    explicit = load_config(environ=BASE_ENV, dotenv_path=None, output_dir=tmp_path)
    assert explicit.output_dir == tmp_path


def test_redact_secrets_masks_values():
    config = load_config(
        environ={**BASE_ENV, "BILI_COOKIE": "SESSDATA=topsecret"}, dotenv_path=None
    )
    message = (
        f"endpoint ok but key {config.dashscope_api_key} and cookie "
        f"{config.bili_cookie} and secret {config.minio_secret_key}"
    )

    redacted = redact_secrets(message, config)

    assert "sk-dashscope-secret" not in redacted
    assert "topsecret" not in redacted
    assert "secret-secret" not in redacted
    assert "***" in redacted
