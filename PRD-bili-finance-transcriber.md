# Bilibili Finance Transcriber PRD

## Problem Statement

用户长期关注多个财经类 B 站 UP 主。这些视频会讨论宏观经济、政策、行业、公司、资产价格和市场风险，但逐个观看耗时较长，也不方便横向比较不同 UP 主的共识、分歧和建议。

用户需要一个仅运行于 macOS 的本地命令行应用：输入一个或多个 B 站 UP 主 UID，应用依次找到每位 UP 主发布时间最新的视频，提取 P1 音频，生成完整中文转写和单 UP 内容汇总，最后综合所有成功结果形成跨 UP 汇总及研究与行动建议。

该应用应把稳定、可重复执行的下载、音频处理、临时存储、语音识别、总结和 Markdown 输出流程封装起来。命令行只显示处理状态，不输出长篇正文。所有结果必须持久化为 Markdown。

## Solution

构建一个以 Python 3.12+ 实现的 macOS CLI 应用。应用接受一个或多个 UID，按输入顺序逐个处理，每个 UID 固定选择发布时间最新的一条视频，不回退到更早视频。

应用使用 `yt-dlp` 获取 UP 主最新视频并下载 P1 最佳音频，使用 `ffmpeg` 转换为单声道、16 kHz、64 kbps MP3。音频上传至现有 MinIO 实例，应用为私有 Bucket 自动创建或配置一天生命周期规则，并生成百炼可访问的预签名 HTTPS URL。

应用统一使用阿里云百炼服务：默认由 `qwen3-asr-flash` 完成音频转写，由 `deepseek-v4-flash` 完成单 UP 汇总和全任务汇总。模型名称允许环境变量覆盖。音频和转写文本均不切分；超过模型限制时明确失败。

每个取得转写的 UID 生成一个 Markdown 文件，合并视频元数据、单 UP 汇总和完整无时间戳转写。所有 UID 处理完成后，应用只使用各单 UP 汇总作为输入生成全任务汇总。全任务汇总负责比较不同 UP 主的共识、分歧、判断条件和内容联系，并由模型给出综合建议。

## User Stories

1. As a 财经内容读者, I want to provide one Bilibili UID, so that I can process that creator's latest video without opening Bilibili manually.
2. As a 财经内容读者, I want to provide multiple UIDs in one command, so that I can collect the latest views from several creators in one task.
3. As a user, I want the application to accept UIDs only, so that the input contract remains simple and unambiguous.
4. As a user, I want each UID to be processed in the order supplied, so that task progress is predictable.
5. As a user, I want each UID occurrence to be processed independently, so that repeated UIDs are not silently removed.
6. As a user, I want the application to select the video with the latest publication time, so that I always receive the creator's newest content.
7. As a user, I want only the latest video to be attempted, so that a failed latest video is not silently replaced by older content.
8. As a user, I want only P1 of a multi-part video processed, so that the behavior remains consistent and bounded.
9. As a user, I want Bilibili access to be anonymous by default, so that login credentials are optional.
10. As a user, I want to configure a Bilibili Cookie string when needed, so that restricted content can be accessed with my account context.
11. As a user, I want Bilibili extraction to use `yt-dlp`, so that metadata and media extraction share one maintained integration.
12. As a user, I want `yt-dlp`'s default retry behavior, so that transient download errors receive ordinary retry handling without custom retry loops.
13. As a user, I want every video processed through the same ASR path, so that output does not depend on inconsistent Bilibili subtitle metadata.
14. As a user, I want the best available P1 audio downloaded, so that ASR receives the clearest practical source.
15. As a user, I want audio normalized to mono, 16 kHz, 64 kbps MP3, so that uploads remain compact and ASR-compatible.
16. As a user, I want local audio stored under the macOS temporary directory, so that project output contains no media files.
17. As a user, I want local temporary audio deleted after success or failure, so that failed tasks do not accumulate local media.
18. As a MinIO operator, I want the application to create the configured Bucket when absent, so that first-run setup is automatic.
19. As a MinIO operator, I want the Bucket to remain private, so that audio is not permanently public.
20. As a MinIO operator, I want uploaded objects to expire after one day, so that abandoned task audio is cleaned automatically.
21. As a MinIO operator, I want lifecycle configuration failures reported as warnings, so that processing may continue when object upload is still possible.
22. As a user, I want MinIO objects named with UID, BV number, timestamp, and UUID, so that concurrent or repeated tasks do not overwrite each other.
23. As a user, I want a temporary HTTPS URL generated for each audio object, so that DashScope can fetch the media.
24. As a user, I want MinIO cleanup controlled solely by lifecycle rules, so that the application does not issue immediate object deletion calls.
25. As a user, I want `qwen3-asr-flash` used by default, so that audio is transcribed through the selected DashScope ASR model.
26. As a user, I want ASR model names configurable by environment variable, so that model upgrades do not require code changes.
27. As a user, I want ASR punctuation preserved, so that the transcript remains readable.
28. As a user, I want speaker diarization disabled, so that the transcript is a simple continuous document.
29. As a user, I want timestamps omitted from the transcript, so that the result is easy to read and summarize.
30. As a user, I want the transcript minimally cleaned, so that whitespace and obvious recognition noise are removed without rewriting meaning.
31. As a user, I want the original simplified or traditional Chinese form preserved, so that the transcript is not converted after recognition.
32. As a user, I want audio sent to ASR without splitting, so that the application does not create segmented media or merge partial transcripts.
33. As a user, I want oversized audio requests to fail explicitly, so that model limits are visible rather than hidden by an unapproved fallback.
34. As a user, I want transcript text sent to summarization without chunking, so that the application follows one simple summarization contract.
35. As a user, I want oversized summarization requests to fail explicitly, so that no partial or hierarchical summary is mistaken for a complete one.
36. As a user, I want `deepseek-v4-flash` used by default for summaries, so that the chosen model generates the analytical output.
37. As a user, I want the summary model configurable by environment variable, so that another DashScope-hosted model can be selected later.
38. As a user, I want every completed UID file to include video title, creator, publication time, BV number, and original URL, so that the source remains identifiable.
39. As a user, I want a single-UP summary to describe the video's main themes, so that I can understand its focus quickly.
40. As a user, I want a single-UP summary to explain macroeconomic and industry background, so that specialized commentary has enough context.
41. As a user, I want a single-UP summary to capture the creator's core judgments, so that their position is not diluted.
42. As a user, I want a single-UP summary to explain impact chains, so that I can see how events may affect industries and markets.
43. As a user, I want a single-UP summary to preserve recommendations made by the creator, including concrete trading views, so that the source's advice is faithfully represented.
44. As a user, I want a single-UP summary to include risks mentioned or implied by the content, so that the argument is not presented without downside.
45. As a user, I want the single-UP summary to remain faithful to that creator, so that the summarization model does not add its own opinion at this stage.
46. As a user, I want the complete transcript appended to the same UID Markdown file, so that source material and summary stay together.
47. As a user, I do not want a separate video-analysis file, so that each UID produces one primary artifact.
48. As a user, I want a partially successful UID file saved when transcription succeeds but summarization fails, so that the expensive transcript is not lost.
49. As a user, I want a failed UID to produce no UID summary file when transcription is unavailable, so that output files represent usable content.
50. As a user, I want one task-wide summary generated even when only one UID succeeds, so that every successful task has a consistent aggregate artifact.
51. As a user, I want the task-wide summary to use single-UP summaries rather than full transcripts, so that aggregate context remains smaller and focused.
52. As a user, I want the task-wide summary to list covered creators and videos, so that I know what evidence it includes.
53. As a user, I want the task-wide summary to identify major macroeconomic and industry themes, so that I can see the task's overall landscape.
54. As a user, I want the task-wide summary to identify frequent consensus views, so that repeated signals are visible.
55. As a user, I want the task-wide summary to expose disagreements and each side's reasoning, so that conflicting views are not forced into false consensus.
56. As a user, I want the task-wide summary to state conditions under which competing judgments may hold, so that disagreement becomes decision-relevant.
57. As a user, I want the task-wide summary to connect events, sectors, and creator arguments, so that cross-video relationships are explicit.
58. As a user, I want the aggregate model to provide research and action recommendations, so that the collected information leads to practical next steps.
59. As a user, I want recommendations allowed to discuss concrete market actions when supported by the supplied summaries, so that useful source conclusions are not automatically suppressed.
60. As a user, I want aggregate risks included, so that recommendations retain downside context.
61. As a user, I do not want external fact checking, so that the first version remains focused on collecting and synthesizing creator content.
62. As a user, I do not want statements labeled as source claims, model inference, or unverified facts, so that the report reads as one integrated analysis.
63. As a user, I want aggregate generation skipped when every UID fails, so that an empty summary is not created.
64. As a user, I want existing UID files preserved if aggregate summarization fails, so that one late failure does not discard completed work.
65. As a user, I want aggregate summarization failure to make the task partially successful, so that the final status accurately reflects the result.
66. As a user, I want output file names to omit video titles, so that path-invalid characters and excessive title lengths cannot break naming.
67. As a user, I want one task timestamp shared across generated files, so that artifacts from the same run can be associated.
68. As a user, I want UID output stored under a directory named by UID, so that creator-specific artifacts remain organized.
69. As a user, I want the output root configurable with `--output-dir`, so that artifacts can be placed in a chosen location.
70. As a user, I want Markdown saving to be mandatory, so that a successful command always leaves usable results.
71. As a user, I want the CLI to show progress and statuses only, so that full transcripts do not flood the terminal.
72. As a user, I want per-UID errors displayed without stopping later UIDs, so that one failure does not invalidate a batch.
73. As a user, I want final success, partial-success, and failure counts, so that task outcome is immediately understandable.
74. As a user, I want invalid UID-like inputs handled as individual Bilibili extraction failures, so that local validation does not impose an extra contract.
75. As a user, I want `.env` loading supported, so that credentials and endpoints can be configured persistently.
76. As a user, I want process environment variables to override `.env`, so that CI or shell-level configuration takes precedence.
77. As a user, I want a `.env.example`, so that all required and optional settings are discoverable without exposing secrets.
78. As a repository owner, I want `.env` ignored by version control, so that credentials are not accidentally committed.
79. As a user, I want both an installed `bili-text` command and direct script execution, so that development and normal use are both convenient.
80. As a user, I want startup checks for Python, `yt-dlp`, `ffmpeg`, configuration, and output access, so that missing prerequisites fail before expensive work begins.

## Implementation Decisions

- The deliverable is a standalone macOS CLI application. A future agent Skill may be a thin invocation wrapper, but is not the primary runtime.
- Python 3.12 or later is required.
- The application provides both an installed `bili-text` console command and direct script execution.
- Packaging and dependencies are managed through `pyproject.toml`.
- Python dependencies include DashScope SDK, MinIO SDK, and `python-dotenv`. `yt-dlp` and `ffmpeg` are executable runtime prerequisites; Bilibili operations invoke the `yt-dlp` CLI.
- The command accepts one or more positional UID values and one optional `--output-dir`. It does not support space URLs, video URLs, nickname search, date ranges, video limits, no-save mode, retained audio, or output-language selection.
- Input UID values are not strictly validated locally. Each value is handed to Bilibili extraction and failures are isolated per item.
- UID occurrences are processed sequentially and are not deduplicated.
- For each UID, the application selects the video with the latest publication time. It does not filter by content type and does not fall back to an earlier video.
- Only P1 is processed. The output metadata notes that only P1 was handled when the source is multi-part.
- All Bilibili access and media extraction use `yt-dlp`; no Bilibili API fallback is maintained.
- Anonymous Bilibili access is the default. When `BILI_COOKIE` exists, it is passed directly as a Cookie request header to `yt-dlp`.
- Bilibili subtitle discovery and download are excluded. Every video follows the ASR path.
- `yt-dlp` downloads the best available P1 audio. `ffmpeg` produces a mono, 16 kHz, 64 kbps MP3.
- Each command invocation creates an isolated macOS temporary workspace. Local audio and intermediate files are removed after each UID regardless of outcome.
- MinIO configuration consists of `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_ACCESS_KEY`, and `MINIO_SECRET_KEY`.
- `MINIO_ENDPOINT` must be a publicly reachable HTTPS API endpoint suitable for access by DashScope. It must not be the MinIO management console URL.
- The application checks for the configured Bucket and creates it when absent. The Bucket is private.
- The application applies a one-day object expiration lifecycle rule to the configured Bucket. Existing lifecycle rules do not need to be preserved. A lifecycle configuration failure is a warning rather than a task-stopping error.
- The configured Bucket should therefore be dedicated to this application's temporary audio.
- MinIO object keys use a `bili-skill/{UID}/{BV}/{timestamp}-{UUID}.mp3` shape.
- The application does not delete MinIO objects after recognition. Lifecycle expiration is the sole remote cleanup mechanism.
- The application generates a time-limited presigned HTTPS URL and supplies it to DashScope ASR.
- `DASHSCOPE_API_KEY` is required for both transcription and summarization.
- ASR defaults to `qwen3-asr-flash`, overridden by `ASR_MODEL`.
- Summarization defaults to `deepseek-v4-flash`, overridden by `SUMMARY_MODEL`.
- ASR retains punctuation, disables speaker diarization, and returns a transcript without sentence-level or word-level timestamps.
- Transcript cleanup is limited to removing timestamps if returned, normalizing whitespace, and removing obvious recognition artifacts. It must not paraphrase the transcript or convert between simplified and traditional Chinese.
- Audio is never split. Transcript text is never chunked. Model size or duration limit errors are surfaced explicitly.
- Each UID has three states: `success` when transcript and single-UP summary complete; `partial` when transcript completes but summary fails; `failed` when no usable transcript is obtained.
- A partial UID produces a Markdown file containing metadata, a clear summary error notice, and the complete transcript.
- A failed UID produces no Markdown artifact.
- The single-UP summary is generated from the complete transcript and source metadata. It remains faithful to the creator and does not add independent model recommendations.
- The single-UP summary includes main themes, macroeconomic and industry background, core judgments, impact chains, creator recommendations, and risks.
- A UID Markdown artifact combines source metadata, the single-UP summary, and the complete transcript in one file.
- A task uses one timezone-aware timestamp generated at startup. UID files are written beneath the UID directory using `{timestamp}-{BV}.md`. Titles remain in document metadata, not file names.
- After sequential UID processing, the aggregate summary receives only successful or partial single-UP summaries. Complete transcripts are not included in the aggregate prompt.
- Partial UIDs whose single-UP summary was not generated cannot contribute substantive content to the aggregate prompt.
- The aggregate report is generated when at least one usable single-UP summary exists, including single-UID tasks.
- The aggregate report includes coverage, main themes, consensus, disagreements and reasoning, conditions for competing views, cross-topic relationships, integrated impact, model-generated research and action recommendations, and risks.
- The aggregate model may faithfully preserve concrete transaction-oriented recommendations contained in creator summaries and may provide its own integrated recommendations. It must not fabricate source data.
- The application performs no external fact checking and does not label individual statements by provenance or verification status.
- If aggregate generation fails, completed UID files remain intact, no incomplete aggregate file is written, and the overall task is partial.
- Aggregate output is written at the output root using `{timestamp}-summary.md`.
- Markdown is always saved. The terminal never prints report bodies or full transcripts.
- The terminal reports startup checks, per-UID stage progress, per-UID final state, concise errors, aggregate state, and final counts.
- `.env` in the working project is loaded when present. Existing process environment variables take precedence.
- `.env.example` documents all variables without real credentials. `.env` is excluded from version control.
- The application architecture separates command orchestration, Bilibili extraction, audio conversion, MinIO storage, DashScope transcription, summarization, domain models, and Markdown rendering behind explicit interfaces.
- Error messages must redact `DASHSCOPE_API_KEY`, MinIO credentials, and the Cookie value even though the Cookie is passed directly to the child process.

## Testing Decisions

- Tests assert externally visible behavior at the highest practical seam: command exit result, terminal status events, external command/API requests, generated Markdown, and cleanup outcomes. Tests should not assert private helper call order when the same behavior can be verified through a public module or CLI boundary.
- The primary test seam is the CLI orchestration layer with `yt-dlp`, `ffmpeg`, MinIO, DashScope ASR, and DashScope chat replaced by deterministic fakes. This covers full state transitions without network access or large media fixtures.
- A successful single-UID acceptance test verifies latest-video selection, P1-only metadata, audio conversion parameters, MinIO upload key, ASR URL submission, single-UP summary content, combined UID Markdown, aggregate Markdown, and terminal counts.
- A successful multi-UID acceptance test verifies strict sequential processing, one artifact per successful UID, one shared task timestamp, aggregate input based on UP summaries, and final counts.
- Failure-isolation tests verify that extraction, download, conversion, upload, ASR, or summary failure for one UID does not prevent later UIDs from running.
- State tests cover `success`, `partial`, and `failed`, including artifact creation rules for each state.
- Latest-video tests provide unordered publication metadata and verify selection by publication time rather than listing or pinned order.
- No-fallback tests verify that failure of the chosen latest video does not trigger processing of an older item.
- Multi-part tests verify that only P1 is selected and the output notes that decision.
- Cookie tests verify anonymous operation when absent and one Cookie header when configured, while ensuring status and exceptions do not expose the value.
- Audio tests verify the observable `ffmpeg` arguments for mono, 16 kHz, 64 kbps MP3 and verify failure propagation.
- Temporary-workspace tests verify local cleanup after success and after exceptions.
- MinIO contract tests verify Bucket creation when absent, private operation, lifecycle application, object naming, presigned URL generation, and upload failure behavior.
- Lifecycle warning tests verify that lifecycle configuration failure is visible but does not stop processing when upload remains possible.
- MinIO tests verify that the application does not issue an object deletion request after completion.
- ASR contract tests verify default and overridden model names, URL input, punctuation behavior, disabled diarization, timestamp omission, and explicit model-limit failures.
- Transcript-cleaning tests use representative timestamped and whitespace-heavy outputs and assert minimal cleanup without wording or script conversion.
- Summary contract tests verify default and overridden model names and validate that required sections are represented in parsed model output.
- Single-UP prompt tests verify that model-authored independent advice is excluded from the requested schema while creator recommendations are retained.
- Aggregate prompt tests verify that only available single-UP summaries are sent, never complete transcripts.
- Aggregate content tests cover consensus, disagreement, supporting reasoning, conditions, cross-topic relationships, recommendations, and risks.
- Aggregate failure tests verify preservation of UID files, absence of a partial aggregate file, and partial final status.
- All-failed tests verify that no aggregate file is generated and final counts are correct.
- Output naming tests verify timezone-aware timestamp use, UID directories, BV-based names, title omission, and `--output-dir` behavior.
- Configuration tests verify `.env` loading, process-environment precedence, missing required variables, malformed endpoint handling, and prerequisite checks.
- Markdown renderer tests compare semantic sections and metadata rather than fragile whole-file snapshots. Small focused snapshots may be used for stable heading structure.
- Real-service smoke tests are optional and manually invoked. They require a disposable UID/video, a dedicated MinIO Bucket, and funded DashScope credentials. Automated tests must not depend on Bilibili, MinIO, or DashScope availability.
- The existing `last30days-cn` project provides prior art for dataclass-style normalized models, Markdown rendering, subprocess-oriented source collection, and per-source error isolation. It does not provide prior art for actual Bilibili transcription and must not be treated as an ASR implementation.

## Out of Scope

- A Codex Skill as the primary implementation.
- A web UI, desktop GUI, mobile application, daemon, backend API, or monitoring service.
- Windows or Linux support in the first release.
- Bilibili nickname search, fuzzy search, space URLs, and direct video URLs.
- Date-range processing, arbitrary video limits, watchlists, scheduled monitoring, processing history, SQLite, or other persistent application state.
- Processing more than the latest video for each UID.
- Falling back to older videos when the latest video fails.
- Processing multi-part content beyond P1.
- Bilibili comments, danmaku, views, likes, coins, favorites, or other engagement metrics.
- Bilibili subtitle retrieval, subtitle language detection, and subtitle/ASR prioritization.
- Retaining local audio or video output.
- Immediate deletion of MinIO audio objects.
- Alibaba Cloud OSS or development of a custom file relay server.
- Audio splitting, transcript chunking, hierarchical summarization, or automatic fallback models.
- Speaker diarization and timestamps in final transcripts.
- Simplified/traditional Chinese conversion.
- Separate per-video analysis files, quotations, and key-facts/data sections.
- A `--no-save`, `--keep-audio`, `--days`, `--limit`, or `--summary-language` option.
- External web research, source verification, financial-data enrichment, or explicit provenance labels.
- Personalized risk profiling or guarantees regarding investment suitability, accuracy, or returns.
- Preservation or merging of pre-existing MinIO lifecycle policies in the configured Bucket.

## Further Notes

- The configured MinIO endpoint must be reachable from Alibaba Cloud DashScope over the public internet. A private LAN address, localhost endpoint, self-signed certificate, or management-console URL will not work.
- Because remote objects are lifecycle-managed rather than immediately deleted, the Bucket should contain only disposable application audio. MinIO lifecycle execution is asynchronous and may remove objects later than exactly 24 hours.
- Passing `BILI_COOKIE` directly as a child-process argument/header may expose it through local process inspection on macOS. This is an accepted first-version tradeoff, but logs and exceptions must still avoid echoing it.
- Model identifiers and exact request schemas should be validated against the installed DashScope SDK and current official Model Studio documentation during implementation. If `qwen3-asr-flash` requires a different DashScope API surface from legacy Paraformer transcription, the ASR adapter must follow the model-specific API while preserving this PRD's URL-input contract.
- The aggregate report is interpretive output based only on creator summaries. It is not independently fact-checked financial research.
- Recommended implementation order is: CLI/configuration and models; Bilibili metadata selection; audio conversion; MinIO integration; ASR integration; UID Markdown; single-UP summarization; aggregate summarization; failure isolation and acceptance tests.
