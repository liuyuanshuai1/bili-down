from http import HTTPStatus

import pytest
from dashscope.api_entities.dashscope_response import TranscriptionResponse

from bili_text.config import DEFAULT_ASR_MODEL, load_config
from bili_text.transcription import (
    FILE_ASYNC_ASR_MODEL,
    DashScopeTranscriber,
    TranscriptionError,
    clean_transcript,
    extract_transcript_text,
    resolve_asr_model,
    transcription_result_url,
)

BASE_ENV = {
    "DASHSCOPE_API_KEY": "sk-dashscope-secret",
    "MINIO_ENDPOINT": "https://minio.example.com",
    "MINIO_BUCKET": "bili-text-audio",
    "MINIO_ACCESS_KEY": "access-secret",
    "MINIO_SECRET_KEY": "secret-secret",
}


def _config(**overrides):
    return load_config(environ={**BASE_ENV, **overrides}, dotenv_path=None)


def _response(**output) -> TranscriptionResponse:
    return TranscriptionResponse(
        status_code=HTTPStatus.OK,
        request_id="req-1",
        code=None,
        message=None,
        output=output,
        usage=None,
        headers={},
    )


def test_resolve_asr_model_maps_default_to_file_async():
    assert resolve_asr_model(DEFAULT_ASR_MODEL) == FILE_ASYNC_ASR_MODEL
    assert resolve_asr_model("custom-asr") == "custom-asr"


def test_clean_transcript_strips_timestamps_and_whitespace_without_rewriting():
    raw = "[00:01:23]  欢迎   使用\n\n\n阿里云。[???]"

    cleaned = clean_transcript(raw)

    assert cleaned == "欢迎 使用\n\n阿里云。"
    assert "00:01:23" not in cleaned
    assert "[???]" not in cleaned


def test_clean_transcript_preserves_simplified_characters():
    traditional = "這是繁體測試。"
    assert clean_transcript(traditional) == traditional


def test_extract_transcript_text_from_result_json():
    payload = {
        "transcripts": [
            {
                "channel_id": 0,
                "text": "欢迎使用阿里云。",
                "sentences": [{"text": "欢迎使用阿里云。", "begin_time": 0}],
            }
        ]
    }

    assert extract_transcript_text(payload) == "欢迎使用阿里云。"


def test_transcription_result_url_requires_succeeded_task():
    ok = _response(task_status="SUCCEEDED", result={"transcription_url": "https://example.com/r.json"})
    assert transcription_result_url(ok) == "https://example.com/r.json"

    failed = _response(task_status="FAILED", message="audio duration exceeds limit")
    with pytest.raises(TranscriptionError, match="ASR model limit exceeded"):
        transcription_result_url(failed)


def test_transcribe_uses_url_input_and_default_model(capsys):
    calls: list[tuple[str, str]] = []

    def submit(model: str, audio_url: str, config):
        calls.append((model, audio_url))
        return _response(
            task_status="SUCCEEDED",
            result={"transcription_url": "https://example.com/result.json"},
        )

    def fetch(_url: str):
        return {"transcripts": [{"text": "完整转写文本。"}]}

    transcriber = DashScopeTranscriber(submit_and_wait=submit, fetch_json=fetch)
    text = transcriber.transcribe(
        "https://minio.example.com/bucket/audio.mp3?sig=abc",
        _config(),
    )

    assert text == "完整转写文本。"
    assert calls == [(FILE_ASYNC_ASR_MODEL, "https://minio.example.com/bucket/audio.mp3?sig=abc")]


def test_transcribe_honors_asr_model_override():
    calls: list[str] = []

    def submit(model: str, _audio_url: str, _config):
        calls.append(model)
        return _response(
            task_status="SUCCEEDED",
            result={"transcription_url": "https://example.com/result.json"},
        )

    transcriber = DashScopeTranscriber(
        submit_and_wait=submit,
        fetch_json=lambda _url: {"transcripts": [{"text": "ok"}]},
    )
    transcriber.transcribe("https://example.com/a.mp3", _config(ASR_MODEL="custom-asr"))

    assert calls == ["custom-asr"]


def test_transcribe_limit_failure_is_explicit():
    def submit(_model: str, _audio_url: str, _config):
        return _response(task_status="FAILED", message="audio duration exceeds model limit")

    transcriber = DashScopeTranscriber(submit_and_wait=submit)

    with pytest.raises(TranscriptionError, match="ASR model limit exceeded"):
        transcriber.transcribe("https://example.com/a.mp3", _config())


def test_transcribe_redacts_api_key_in_runtime_errors():
    def submit(_model: str, _audio_url: str, _config):
        raise RuntimeError("boom sk-dashscope-secret")

    transcriber = DashScopeTranscriber(submit_and_wait=submit)

    with pytest.raises(TranscriptionError) as excinfo:
        transcriber.transcribe("https://example.com/a.mp3", _config())

    assert "sk-dashscope-secret" not in str(excinfo.value)
