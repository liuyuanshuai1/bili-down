"""Markdown rendering for UID and aggregate artifacts."""

from __future__ import annotations

from datetime import datetime

from .models import VideoMetadata


def _format_publish_time(value: datetime) -> str:
    return value.isoformat()


class MarkdownRendererImpl:
    """Renders UID and aggregate Markdown with stable heading structure."""

    def render_uid(
        self,
        metadata: VideoMetadata,
        summary: str | None,
        transcript: str,
        *,
        summary_error: str | None = None,
    ) -> str:
        lines = [
            f"# {metadata.title}",
            "",
            "## 源信息",
            "",
            f"- UID: {metadata.uid}",
            f"- BV 号: {metadata.bv}",
            f"- UP 主: {metadata.creator}",
            f"- 发布时间: {_format_publish_time(metadata.publish_time)}",
            f"- 原始链接: {metadata.url}",
        ]
        if metadata.is_multipart:
            lines.append("- 说明: 本任务仅处理 P1（多分 P 视频的第一段）")
        lines.extend(["", "## 单 UP 汇总", ""])
        if summary is not None:
            lines.append(summary)
        elif summary_error is not None:
            lines.extend(
                [
                    "> **汇总失败**",
                    ">",
                    f"> {summary_error}",
                ]
            )
        else:
            lines.append("_（无汇总）_")
        lines.extend(["", "## 完整转写", "", transcript, ""])
        return "\n".join(lines)

    def render_aggregate(
        self,
        report: str,
        *,
        covered: list[tuple[str, str, str]],
        task_timestamp: datetime,
    ) -> str:
        lines = [
            "# 全任务汇总",
            "",
            "## 覆盖范围",
            "",
            f"- 任务时间戳: {task_timestamp.isoformat()}",
        ]
        for uid, bv, title in covered:
            lines.append(f"- UID {uid} / {bv}: {title}")
        lines.extend(["", "## 综合分析", "", report, ""])
        return "\n".join(lines)
