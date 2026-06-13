from datetime import UTC, datetime

from bili_text.markdown import MarkdownRendererImpl
from bili_text.models import VideoMetadata


def _metadata(**overrides) -> VideoMetadata:
    defaults = dict(
        uid="12345",
        bv="BVfake12345",
        title="宏观展望：2026 下半年",
        creator="财经博主甲",
        publish_time=datetime(2026, 6, 1, 8, 30, tzinfo=UTC),
        url="https://www.bilibili.com/video/BVfake12345",
        is_multipart=False,
    )
    defaults.update(overrides)
    return VideoMetadata(**defaults)


def test_uid_markdown_includes_metadata_sections_and_transcript():
    renderer = MarkdownRendererImpl()
    body = renderer.render_uid(
        _metadata(),
        "### 主要主题\n\n通胀与利率。",
        "完整转写正文。",
    )

    assert "## 源信息" in body
    assert "BVfake12345" in body
    assert "财经博主甲" in body
    assert "## 单 UP 汇总" in body
    assert "通胀与利率" in body
    assert "## 完整转写" in body
    assert "完整转写正文。" in body
    assert "# 宏观展望：2026 下半年" in body


def test_uid_markdown_notes_multipart_and_partial_summary_error():
    renderer = MarkdownRendererImpl()
    body = renderer.render_uid(
        _metadata(is_multipart=True),
        None,
        "仅有转写。",
        summary_error="model limit exceeded",
    )

    assert "仅处理 P1" in body
    assert "汇总失败" in body
    assert "model limit exceeded" in body
    assert "## 完整转写" in body


def test_aggregate_markdown_includes_coverage_and_report():
    renderer = MarkdownRendererImpl()
    task_ts = datetime(2026, 6, 12, 15, 0, tzinfo=UTC)
    body = renderer.render_aggregate(
        "### 共识\n\n看多科技。",
        covered=[("111", "BV111", "标题一"), ("222", "BV222", "标题二")],
        task_timestamp=task_ts,
    )

    assert "# 全任务汇总" in body
    assert "## 覆盖范围" in body
    assert "UID 111 / BV111" in body
    assert "## 综合分析" in body
    assert "看多科技" in body
