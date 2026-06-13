# Context: Bilibili Finance Transcriber

本文件定义本仓库的领域术语（glossary）与核心约定。Issue、计划、测试与实现都应使用此处定义的术语，保持多 agent 协作的一致性。与既有 ADR（若存在于 `docs/adr/`）冲突时，应显式指出而非默默覆盖。

## 一句话定位

一个**仅运行于 macOS 的本地命令行应用**：输入一个或多个 B 站 UP 主 UID，对每位 UP 主**发布时间最新**的一条视频提取 P1 音频，经语音识别生成中文转写与单 UP 汇总，最后跨 UP 生成全任务汇总。所有结果持久化为 Markdown，命令行只显示状态。

## 核心名词

| 术语 | 英文 / 标识 | 含义 |
| --- | --- | --- |
| UP 主 | creator | B 站内容创作者。本应用关注财经类 UP 主。 |
| UID | UID | UP 主的数字用户 ID，是本应用唯一接受的输入形式。 |
| BV 号 | BV number | B 站视频的稳定标识（如 `BV1xx411x7xx`），用于产物命名与对象键。 |
| P1 | P1 | 多分 P 视频的第一个分段。本应用**只处理 P1**。 |
| 最新视频 | latest video | 某 UID 下**发布时间**最新的一条视频；不按列表/置顶顺序，不回退到更早视频。 |
| 转写 | transcript | 由 ASR 生成的完整中文文本，无时间戳、无说话人分离，仅做最小清洗。 |
| 单 UP 汇总 | single-UP summary | 针对单个 UID 的内容汇总，忠实于该 UP 主，不加入模型独立建议。 |
| 全任务汇总 / 聚合 | task-wide / aggregate summary | 跨所有成功 UID 的综合报告，**仅以单 UP 汇总为输入**，可给出模型综合建议。 |
| 任务 | task | 一次命令调用，处理给定的全部 UID。 |
| 任务时间戳 | task timestamp | 任务启动时生成的单一时区感知时间戳，所有产物共享。 |
| UID 产物 | UID artifact | 单个 UID 的 Markdown 文件，合并源元数据 + 单 UP 汇总 + 完整转写。 |
| 聚合产物 | aggregate artifact | 全任务汇总的 Markdown 文件。 |

## 处理状态（三态）

每个 UID 的处理结果恰为以下之一：

| 状态 | 标识 | 条件 | 产物 |
| --- | --- | --- | --- |
| 成功 | `success` | 转写与单 UP 汇总均完成 | 完整 UID 产物（元数据 + 汇总 + 转写） |
| 部分成功 | `partial` | 转写完成但单 UP 汇总失败 | UID 产物（元数据 + 汇总错误提示 + 完整转写） |
| 失败 | `failed` | 未取得可用转写 | 不产出 UID 产物 |

任务整体状态在以下情况判为 `partial`：聚合生成失败但存在已完成的 UID 产物。

## 外部依赖与集成

| 名称 | 角色 |
| --- | --- |
| `yt-dlp` | 可执行运行时前置；**唯一**的 Bilibili 元数据与媒体提取通道，不维护 API 回退。 |
| `ffmpeg` | 可执行运行时前置；将 P1 音频转为单声道、16 kHz、64 kbps MP3。 |
| MinIO | 对象存储；私有桶 + 一天生命周期；存放临时音频并产出预签名 HTTPS URL。 |
| DashScope（阿里云百炼） | 统一 AI 服务；提供 ASR 与汇总能力。 |
| 预签名 URL | presigned URL | MinIO 生成的限时 HTTPS URL，供 DashScope ASR 拉取音频。 |
| 生命周期规则 | lifecycle rule | 桶上的一天对象过期规则，是远端清理的**唯一**机制（不主动删除对象）。 |

## 模型约定

| 用途 | 默认模型 | 覆盖环境变量 |
| --- | --- | --- |
| ASR 转写 | `qwen3-asr-flash` | `ASR_MODEL` |
| 汇总（单 UP 与聚合） | `deepseek-v4-flash` | `SUMMARY_MODEL` |

约束：音频**不切分**、转写文本**不分块**；超模型限制时**显式失败**，不做未经批准的回退或分层汇总。

## 配置变量

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 是 | 转写与汇总共用。 |
| `MINIO_ENDPOINT` | 是 | 公网可达的 HTTPS **API** 端点（非管理控制台 URL）。 |
| `MINIO_BUCKET` | 是 | 专用于本应用临时音频的桶。 |
| `MINIO_ACCESS_KEY` | 是 | MinIO 凭据。 |
| `MINIO_SECRET_KEY` | 是 | MinIO 凭据。 |
| `BILI_COOKIE` | 否 | 存在时作为 Cookie 请求头直接传给 `yt-dlp`；默认匿名访问。 |
| `ASR_MODEL` | 否 | 覆盖默认 ASR 模型。 |
| `SUMMARY_MODEL` | 否 | 覆盖默认汇总模型。 |

配置加载：读取工作目录 `.env`，进程环境变量优先于 `.env`。机密（`DASHSCOPE_API_KEY`、MinIO 凭据、Cookie 值）在错误信息与日志中必须脱敏。

## 命名约定

- MinIO 对象键：`bili-skill/{UID}/{BV}/{timestamp}-{UUID}.mp3`
- UID 产物路径：`{output_dir}/{UID}/{timestamp}-{BV}.md`（标题只进文档元数据，不进文件名）
- 聚合产物路径：`{output_dir}/{timestamp}-summary.md`

## 命令契约

- 入口：已安装的 `bili-text` 控制台命令，或直接脚本执行。
- 参数：一个或多个位置 UID + 可选 `--output-dir`。
- UID 按输入顺序逐个处理，**不去重**；单个 UID 失败不影响后续。
- UID **不做严格本地校验**，非法输入作为单条 Bilibili 提取失败隔离处理。
- 终端只显示启动检查、阶段进度、每 UID 最终状态、简洁错误、聚合状态与最终计数；**不输出报告正文或完整转写**。

## 架构边界

模块按显式接口分离：命令编排、Bilibili 提取、音频转换、MinIO 存储、DashScope 转写、汇总、领域模型、Markdown 渲染。测试以最高可行缝（CLI 编排层）断言外部可见行为，外部依赖以确定性 fake 替换。
