"""DashScope chat summarization for single-UP and aggregate reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus

from dashscope import Generation
from dashscope.api_entities.dashscope_response import GenerationResponse

from .config import AppConfig, redact_secrets
from .interfaces import Summarizer
from .models import VideoMetadata

LIMIT_HINTS = (
    "limit",
    "token",
    "length",
    "too long",
    "context",
    "exceed",
    "超过",
    "超长",
    "上下文",
)

SINGLE_UP_SECTIONS = (
    "### 主要主题",
    "### 宏观经济与行业背景",
    "### 核心判断",
    "### 影响链条",
    "### UP 主建议",
    "### 风险",
)

SINGLE_UP_SYSTEM_PROMPT = """\
你是财经内容整理助手。请仅基于用户提供的视频转写与源信息，生成对该 UP 主内容的单 UP 汇总。

规则：
- 忠实于该 UP 主的原意与表述，不要加入你自己的独立投资建议、额外观点或外部事实
- 使用 Markdown，且必须包含以下小节标题（标题文字保持一致）：
  ### 主要主题
  ### 宏观经济与行业背景
  ### 核心判断
  ### 影响链条
  ### UP 主建议
  ### 风险
- 「UP 主建议」中如实保留 UP 主提出的具体交易、仓位或操作观点（如有）
- 不要请求分段；用户会提供完整转写，请基于全文汇总
"""

AGGREGATE_SECTIONS = (
    "### 主要主题",
    "### 共识",
    "### 分歧与理由",
    "### 竞争判断的成立条件",
    "### 跨主题联系",
    "### 综合影响",
    "### 研究与行动建议",
    "### 风险",
)

AGGREGATE_SYSTEM_PROMPT = """\
你是财经内容综合分析助手。请仅基于用户提供的单 UP 汇总，生成跨 UP 主的全任务综合报告。

规则：
- 输入只有单 UP 汇总，不包含完整转写；不要假设或编造未在汇总中出现的信息
- 使用 Markdown，且必须包含以下小节标题（标题文字保持一致）：
  ### 主要主题
  ### 共识
  ### 分歧与理由
  ### 竞争判断的成立条件
  ### 跨主题联系
  ### 综合影响
  ### 研究与行动建议
  ### 风险
- 可比较不同 UP 主的共识、分歧、判断条件与跨主题联系
- 在汇总证据支持时，可忠实保留具体交易导向建议，并给出你综合后的研究与行动建议
- 不要进行外部事实核查，不要给单条陈述加来源/推断/未核实标签
- 报告应读作一体化分析，而不是逐条标注出处的清单
"""


class SummarizationError(Exception):
    """Raised when DashScope summarization fails or returns unusable output."""


GenerateFn = Callable[[str, list[dict[str, str]], AppConfig], GenerationResponse]


def _limit_message(message: str) -> str:
    lowered = message.lower()
    if any(hint in lowered or hint in message for hint in LIMIT_HINTS):
        return f"Summary model limit exceeded: {message}"
    return message


def build_single_up_user_prompt(transcript: str, metadata: VideoMetadata) -> str:
    publish_time = metadata.publish_time.isoformat()
    multipart_note = (
        "\n- 说明: 本视频为多分 P，本次仅处理 P1"
        if metadata.is_multipart
        else ""
    )
    return (
        "请为以下视频生成单 UP 汇总。\n\n"
        "## 源信息\n"
        f"- UP 主: {metadata.creator}\n"
        f"- UID: {metadata.uid}\n"
        f"- BV 号: {metadata.bv}\n"
        f"- 标题: {metadata.title}\n"
        f"- 发布时间: {publish_time}\n"
        f"- 原始链接: {metadata.url}"
        f"{multipart_note}\n\n"
        "## 完整转写\n"
        f"{transcript}"
    )


def validate_single_up_sections(text: str) -> None:
    missing = [section for section in SINGLE_UP_SECTIONS if section not in text]
    if missing:
        raise SummarizationError(
            "summary missing required sections: " + ", ".join(missing)
        )


def build_aggregate_user_prompt(summaries: list[str]) -> str:
    blocks = [
        f"## 单 UP 汇总 {index}\n\n{summary}"
        for index, summary in enumerate(summaries, start=1)
    ]
    return (
        "请基于以下单 UP 汇总生成全任务综合报告。\n"
        "注意：输入不包含完整转写，请仅使用这些汇总中的信息。\n\n"
        + "\n\n".join(blocks)
    )


def validate_aggregate_sections(text: str) -> None:
    missing = [section for section in AGGREGATE_SECTIONS if section not in text]
    if missing:
        raise SummarizationError(
            "aggregate report missing required sections: " + ", ".join(missing)
        )


def extract_generation_text(response: GenerationResponse) -> str:
    if response.status_code != HTTPStatus.OK:
        detail = response.message or response.code or "summarization request failed"
        raise SummarizationError(_limit_message(str(detail)))

    output = response.output
    if output is None:
        raise SummarizationError("summarization returned no output")

    text = output.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    choices = output.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
        else:
            message = getattr(first, "message", None)
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()

    raise SummarizationError("summarization returned empty content")


def _default_generate(
    model: str, messages: list[dict[str, str]], config: AppConfig
) -> GenerationResponse:
    return Generation.call(
        model=model,
        api_key=config.dashscope_api_key,
        messages=messages,
        result_format="message",
    )


@dataclass
class DashScopeSummarizer:
    """Generates single-UP and aggregate summaries via DashScope chat models."""

    generate: GenerateFn | None = None

    def _generate_summary(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        config: AppConfig,
        validate: Callable[[str], None],
    ) -> str:
        generate = self.generate or _default_generate
        try:
            response = generate(model, messages, config)
            summary = extract_generation_text(response)
            validate(summary)
        except SummarizationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SummarizationError(redact_secrets(str(exc), config)) from exc
        return summary

    def summarize_single(
        self, transcript: str, metadata: VideoMetadata, config: AppConfig
    ) -> str:
        if not transcript.strip():
            raise SummarizationError("empty transcript")

        messages = [
            {"role": "system", "content": SINGLE_UP_SYSTEM_PROMPT},
            {"role": "user", "content": build_single_up_user_prompt(transcript, metadata)},
        ]
        return self._generate_summary(
            model=config.summary_model,
            messages=messages,
            config=config,
            validate=validate_single_up_sections,
        )

    def summarize_aggregate(self, summaries: list[str], config: AppConfig) -> str:
        usable = [summary.strip() for summary in summaries if summary and summary.strip()]
        if not usable:
            raise SummarizationError("no usable single-UP summaries for aggregate report")

        messages = [
            {"role": "system", "content": AGGREGATE_SYSTEM_PROMPT},
            {"role": "user", "content": build_aggregate_user_prompt(usable)},
        ]
        return self._generate_summary(
            model=config.summary_model,
            messages=messages,
            config=config,
            validate=validate_aggregate_sections,
        )


@dataclass
class CompositeSummarizer:
    """Combines real single-UP summarization with a placeholder aggregate backend."""

    single: Summarizer
    aggregate: Summarizer

    def summarize_single(
        self, transcript: str, metadata: VideoMetadata, config: AppConfig
    ) -> str:
        return self.single.summarize_single(transcript, metadata, config)

    def summarize_aggregate(self, summaries: list[str], config: AppConfig) -> str:
        return self.aggregate.summarize_aggregate(summaries, config)
