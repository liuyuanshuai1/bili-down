"""DashScope ASR transcription via ``QwenTranscription``."""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from dashscope.api_entities.dashscope_response import TranscriptionResponse
from dashscope.audio.qwen_asr import QwenTranscription

from .config import AppConfig, redact_secrets

# File-URL async API model id (see DashScope Model Studio docs).
FILE_ASYNC_ASR_MODEL = "qwen3-asr-flash-filetrans"

LIMIT_HINTS = (
    "limit",
    "duration",
    "too long",
    "size",
    "exceed",
    "超过",
    "时长",
    "大小",
    "超长",
)

TIMESTAMP_PATTERNS = (
    re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]"),
    re.compile(
        r"\d{1,2}:\d{2}:\d{2}[,.]?\d*\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]?\d*"
    ),
)


class TranscriptionError(Exception):
    """Raised when DashScope ASR fails or returns unusable output."""


UrlFetcher = Callable[[str], dict[str, Any]]
SubmitAndWait = Callable[[str, str, AppConfig], TranscriptionResponse]


def resolve_asr_model(model: str) -> str:
    """Map PRD default model id to the file-URL async API model when needed."""
    if model == "qwen3-asr-flash":
        return FILE_ASYNC_ASR_MODEL
    return model


def _limit_message(message: str) -> str:
    lowered = message.lower()
    if any(hint in lowered or hint in message for hint in LIMIT_HINTS):
        return f"ASR model limit exceeded: {message}"
    return message


def clean_transcript(text: str) -> str:
    """Minimal cleanup: strip timestamps/whitespace/noise without rewriting meaning."""
    cleaned = text
    for pattern in TIMESTAMP_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = cleaned.replace("[???]", "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_transcript_text(payload: dict[str, Any]) -> str:
    transcripts = payload.get("transcripts")
    if not isinstance(transcripts, list) or not transcripts:
        raise TranscriptionError("ASR result JSON contains no transcripts")

    parts: list[str] = []
    for item in transcripts:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    if not parts:
        raise TranscriptionError("ASR result JSON contains no transcript text")
    return "\n".join(parts)


def transcription_result_url(response: TranscriptionResponse) -> str:
    if response.status_code != HTTPStatus.OK:
        detail = response.message or response.code or "ASR request failed"
        raise TranscriptionError(_limit_message(str(detail)))

    output = response.output
    if output is None:
        raise TranscriptionError("ASR returned no output")

    status = output.get("task_status")
    if status == "FAILED":
        message = output.get("message") or output.get("code") or "ASR task failed"
        raise TranscriptionError(_limit_message(str(message)))
    if status != "SUCCEEDED":
        raise TranscriptionError(f"ASR task ended with unexpected status: {status}")

    result = output.get("result")
    if not isinstance(result, dict):
        raise TranscriptionError("ASR succeeded but returned no result")

    url = result.get("transcription_url")
    if not isinstance(url, str) or not url:
        raise TranscriptionError("ASR succeeded but missing transcription_url")
    return url


def _default_fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise TranscriptionError("ASR result JSON must be an object")
    return payload


def _default_submit_and_wait(
    model: str, audio_url: str, config: AppConfig
) -> TranscriptionResponse:
    task = QwenTranscription.async_call(
        model=model,
        file_url=audio_url,
        api_key=config.dashscope_api_key,
        parameters={"channel_id": [0], "enable_itn": False},
    )
    return QwenTranscription.wait(task, api_key=config.dashscope_api_key)


@dataclass
class DashScopeTranscriber:
    """Transcribes presigned audio URLs using DashScope Qwen ASR."""

    submit_and_wait: SubmitAndWait | None = None
    fetch_json: UrlFetcher = _default_fetch_json

    def transcribe(self, audio_url: str, config: AppConfig) -> str:
        model = resolve_asr_model(config.asr_model)
        submit = self.submit_and_wait or _default_submit_and_wait

        try:
            response = submit(model, audio_url, config)
            result_url = transcription_result_url(response)
            payload = self.fetch_json(result_url)
            raw = extract_transcript_text(payload)
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(redact_secrets(str(exc), config)) from exc

        return clean_transcript(raw)
