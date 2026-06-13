from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from dashscope.api_entities.dashscope_response import GenerationResponse

from bili_text.config import DEFAULT_SUMMARY_MODEL, load_config
from bili_text.models import VideoMetadata
from bili_text.summarization import (
    AGGREGATE_SYSTEM_PROMPT,
    SINGLE_UP_SYSTEM_PROMPT,
    CompositeSummarizer,
    DashScopeSummarizer,
    SummarizationError,
    build_aggregate_user_prompt,
    build_single_up_user_prompt,
    extract_generation_text,
    validate_aggregate_sections,
    validate_single_up_sections,
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


def _metadata(**overrides) -> VideoMetadata:
    defaults = dict(
        uid="12345",
        bv="BVtest123",
        title="宏观展望",
        creator="财经博主甲",
        publish_time=datetime(2026, 6, 1, 8, 30, tzinfo=UTC),
        url="https://www.bilibili.com/video/BVtest123",
        is_multipart=False,
    )
    defaults.update(overrides)
    return VideoMetadata(**defaults)


def _full_aggregate() -> str:
    return "\n\n".join(
        [
            "### 主要主题\n\n宏观与科技板块。",
            "### 共识\n\n多位 UP 主关注利率路径。",
            "### 分歧与理由\n\nA 看多成长，B 偏好价值。",
            "### 竞争判断的成立条件\n\n若通胀回落则成长占优。",
            "### 跨主题联系\n\n利率影响估值与板块轮动。",
            "### 综合影响\n\n流动性预期主导短期波动。",
            "### 研究与行动建议\n\n跟踪 CPI 与仓位再平衡。",
            "### 风险\n\n政策与地缘不确定性。",
        ]
    )


def _full_summary() -> str:
    return "\n\n".join(
        [
            "### 主要主题\n\n通胀与利率。",
            "### 宏观经济与行业背景\n\n全球流动性收紧。",
            "### 核心判断\n\n短期震荡。",
            "### 影响链条\n\n利率上行压制估值。",
            "### UP 主建议\n\n建议降低仓位，关注债券。",
            "### 风险\n\n政策超预期变化。",
        ]
    )


def _response(text: str, *, status: int = HTTPStatus.OK) -> GenerationResponse:
    return GenerationResponse(
        status_code=status,
        request_id="req-1",
        code=None,
        message=None,
        output={"choices": [{"message": {"role": "assistant", "content": text}}]},
        usage=None,
        headers={},
    )


def test_single_up_prompt_includes_metadata_and_full_transcript():
    prompt = build_single_up_user_prompt("完整转写正文。", _metadata())

    assert "财经博主甲" in prompt
    assert "BVtest123" in prompt
    assert "完整转写正文。" in prompt
    assert "宏观展望" in prompt


def test_single_up_system_prompt_excludes_independent_model_advice():
    assert "不要加入你自己的独立投资建议" in SINGLE_UP_SYSTEM_PROMPT
    assert "UP 主建议" in SINGLE_UP_SYSTEM_PROMPT


def test_validate_single_up_sections_requires_all_headings():
    validate_single_up_sections(_full_summary())

    with pytest.raises(SummarizationError, match="missing required sections"):
        validate_single_up_sections("### 主要主题\n\n只有一节。")


def test_summarize_single_uses_default_model_and_returns_sections():
    calls: list[tuple[str, list[dict[str, str]]]] = []

    def generate(model, messages, config):
        calls.append((model, messages))
        return _response(_full_summary())

    summarizer = DashScopeSummarizer(generate=generate)
    result = summarizer.summarize_single("转写内容。", _metadata(), _config())

    assert "通胀与利率" in result
    assert calls[0][0] == DEFAULT_SUMMARY_MODEL
    assert calls[0][1][0]["role"] == "system"
    assert "转写内容。" in calls[0][1][1]["content"]


def test_summarize_single_honors_summary_model_override():
    calls: list[str] = []

    def generate(model, _messages, _config):
        calls.append(model)
        return _response(_full_summary())

    summarizer = DashScopeSummarizer(generate=generate)
    summarizer.summarize_single(
        "转写。", _metadata(), _config(SUMMARY_MODEL="custom-summary")
    )

    assert calls == ["custom-summary"]


def test_summarize_single_limit_failure_is_explicit():
    def generate(_model, _messages, _config):
        return GenerationResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            request_id="req-1",
            code="InvalidParameter",
            message="input length exceeds model context limit",
            output=None,
            usage=None,
            headers={},
        )

    summarizer = DashScopeSummarizer(generate=generate)

    with pytest.raises(SummarizationError, match="Summary model limit exceeded"):
        summarizer.summarize_single("长转写。", _metadata(), _config())


def test_summarize_single_redacts_api_key():
    def generate(_model, _messages, _config):
        raise RuntimeError("failed with sk-dashscope-secret")

    summarizer = DashScopeSummarizer(generate=generate)

    with pytest.raises(SummarizationError) as excinfo:
        summarizer.summarize_single("转写。", _metadata(), _config())

    assert "sk-dashscope-secret" not in str(excinfo.value)


def test_extract_generation_text_supports_output_text_field():
    response = GenerationResponse(
        status_code=HTTPStatus.OK,
        request_id="req-1",
        code=None,
        message=None,
        output={"text": "直接文本输出"},
        usage=None,
        headers={},
    )

    assert extract_generation_text(response) == "直接文本输出"


def test_aggregate_prompt_uses_only_single_up_summaries():
    prompt = build_aggregate_user_prompt(["汇总 A", "汇总 B"])

    assert "汇总 A" in prompt
    assert "汇总 B" in prompt
    assert "## 完整转写" not in prompt
    assert "单 UP 汇总 1" in prompt
    assert "单 UP 汇总 2" in prompt


def test_aggregate_system_prompt_allows_integrated_recommendations():
    assert "研究与行动建议" in AGGREGATE_SYSTEM_PROMPT
    assert "不包含完整转写" in AGGREGATE_SYSTEM_PROMPT


def test_validate_aggregate_sections_requires_all_headings():
    validate_aggregate_sections(_full_aggregate())

    with pytest.raises(SummarizationError, match="aggregate report missing required sections"):
        validate_aggregate_sections("### 共识\n\n只有一节。")


def test_summarize_aggregate_uses_summaries_only_and_default_model():
    calls: list[tuple[str, list[dict[str, str]]]] = []

    def generate(model, messages, config):
        calls.append((model, messages))
        return _response(_full_aggregate())

    summarizer = DashScopeSummarizer(generate=generate)
    result = summarizer.summarize_aggregate(["UP 汇总一", "UP 汇总二"], _config())

    assert "利率路径" in result
    assert calls[0][0] == DEFAULT_SUMMARY_MODEL
    assert "UP 汇总一" in calls[0][1][1]["content"]
    assert "## 完整转写" not in calls[0][1][1]["content"]


def test_summarize_aggregate_rejects_empty_input():
    summarizer = DashScopeSummarizer()

    with pytest.raises(SummarizationError, match="no usable single-UP summaries"):
        summarizer.summarize_aggregate([], _config())


def test_composite_summarizer_delegates_aggregate():
    from bili_text.fakes import DeterministicFakes

    fakes = DeterministicFakes()
    composite = CompositeSummarizer(single=DashScopeSummarizer(), aggregate=fakes)

    aggregate = composite.summarize_aggregate(["summary one"], _config())

    assert "共识" in aggregate
