# bili-text

macOS 本地 CLI：输入一个或多个 B 站 UP 主 **UID**，对每位 UP 主**发布时间最新**的 **P1** 视频完成音频提取、语音识别、单 UP 汇总与全任务汇总，所有结果持久化为 Markdown。

## 前置条件

- macOS
- Python 3.12+
- 可执行文件：`yt-dlp`、`ffmpeg`（需在 `PATH` 中）
- 阿里云百炼 DashScope API Key
- 公网可达的 MinIO HTTPS API 端点（供 DashScope 拉取临时音频）

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 配置

```bash
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY、MINIO_* 等
```

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 是 | ASR 与汇总共用 |
| `MINIO_ENDPOINT` | 是 | 公网 HTTPS **API** 端点（非管理控制台） |
| `MINIO_BUCKET` | 是 | 专用于临时音频的桶 |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | 是 | MinIO 凭据 |
| `BILI_COOKIE` | 否 | 需要登录态时传给 `yt-dlp` |
| `ASR_MODEL` | 否 | 默认 `qwen3-asr-flash` |
| `SUMMARY_MODEL` | 否 | 默认 `deepseek-v4-flash` |

进程环境变量优先于 `.env`。

## 用法

```bash
# 单个 UID
bili-text 12345678 --output-dir ./out

# 多个 UID（按顺序处理，不去重）
bili-text 111 222 111 --output-dir ./out

# 或直接运行
python -m bili_text.cli 12345678
```

## 输出

一次任务共享一个时间戳：

```
out/
├── 12345678/
│   └── {timestamp}-BVxxxxxx.md    # 源信息 + 单 UP 汇总 + 完整转写
└── {timestamp}-summary.md         # 全任务汇总
```

终端只显示阶段进度与最终计数，不打印转写正文。

## 开发与测试

```bash
pytest          # 83 项测试（外部依赖均为 fake，无需网络）
ruff check src tests
```

领域术语与架构约定见 [`CONTEXT.md`](CONTEXT.md)。PRD 见 [`PRD-bili-finance-transcriber.md`](PRD-bili-finance-transcriber.md)。

## 手动冒烟

配置真实 `.env` 后，对可丢弃的测试 UID 运行：

```bash
bili-text <UID> --output-dir ./smoke-out
```

确认 `./smoke-out/{UID}/` 与 `./smoke-out/{timestamp}-summary.md` 已生成。
