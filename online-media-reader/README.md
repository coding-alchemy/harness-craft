# 在线媒体文字读取（online-media-reader）

本模块提供一个 Agent Skill（[SKILL.md](./SKILL.md)）及两个执行入口：主读取 [scripts/read.py](./scripts/read.py) 与 ASR 画面复核 [scripts/review.py](./scripts/review.py)。它从抖音、B站和小红书的公开单条链接自适应取得文字内容，输出标明来源的 Markdown。

## 使用

```bash
python3 scripts/read.py <URL> [--output 结果.md] [--keep-media] [--verify-audio] [--whisper-model small]
python3 scripts/read.py <URL> --probe-only
python3 scripts/review.py <run_dir> --corrections <corrections.json>
```

处理路径自适应：脚本在 30 秒总预算内只验证最高优先级的平台字幕（人工 > 自动，中文优先），可靠时直接采用；字幕缺失、不可访问、无效或超时则下载媒体并用 faster-whisper 转写。中文转写会使用标题和作者作为短提示。`--probe-only` 只输出机器可读的字幕可用性决策，不下载媒体或运行 ASR；`--verify-audio` 可在字幕可靠时附加 ASR 核验。小红书图文按页面顺序逐图 PaddleOCR。平台 AI 摘要只作为补充，不替代正文。

视频正文先输出与主字幕轨同源渲染的"完整连续字幕"（无时间戳），随后是带时间戳字幕；复核纠正后两种正文同步更新，不存在两份独立文本。ASR 成为主文字源时，主入口为每个非空 cue 提取有界画面证据帧并返回 `review_required: true`；复核入口校验结构化纠正（全部 cue 已检查、完整替换、证据帧归属正确）后原子重渲染唯一正文。无视觉能力时提交显式 `unavailable`，保留原始 ASR 并如实记录未完成画面复核。

普通运行默认在命令启动目录生成：

```text
.media/<平台>-<内容ID>-<时间>/
├── content.md
├── manifest.json
├── review/                    # 仅 ASR 主路径
│   ├── input.json             # 原始 cue 与证据映射
│   ├── corrections.json       # 复核入口保存的纠正记录
│   └── frames/                # 每个 cue 最多三张证据帧
└── artifacts/source.<ext>     # 仅 --keep-media
```

stdout JSON 的 `result_path` 指向唯一正文，`run_dir` 指向本次运行目录；待复核的 ASR 运行同时返回 `review_required: true` 和 `review_path`，复核入口完成后 stdout 与 `manifest.json` 的 `review_status` 给出终态。成功后中间目录 `work/` 被删除，`review/` 随结果保留，复核临时视频在取帧后删除；失败时 stderr JSON 返回失败 `stage`、`error` 和 `run_dir`，并保留非 Cookie 中间材料。Ctrl-C 同样返回结构化错误并删除 Cookie。`--output` 是显式兼容覆盖，不会额外生成 `content.md`；正文和 `--keep-media` 媒体只有在原子发布成功后才成为正式结果。

遇到登录墙、验证码、私密内容或依赖缺失时报错并指出失败阶段，不自动登录或绕过限制。

## 条件依赖

脚本不自动安装依赖。按实际使用的处理分支配置（[requirements.txt](./requirements.txt)）：

- 字幕直读：无额外依赖；
- 媒体下载：已有可用直连时无需额外下载器，否则使用 `yt-dlp`；抖音匿名会话另需 Playwright 浏览器能力；
- 语音转写：`ffmpeg` 与 `faster-whisper`；
- 图片 OCR：`paddleocr`。

需要安装时先取得用户授权，不默认写入 `/usr/local/bin`。已有依赖按需下载的 Whisper 与 PaddleOCR 模型固定写入执行目录的 `.media/tools/faster-whisper/` 和 `.media/tools/paddleocr/`；OCR 图片格式转换只写入本次运行的 `work/`。

## 测试

```bash
python3 -m pytest tests/ -q
# 也可在仓库根目录运行：python3 -m pytest online-media-reader/tests -q
```

全部测试使用固定样本与假外部命令（临时 PATH 与 `OMR_WHISPER_BIN` / `OMR_OCR_BIN`），不访问真实网络。规格与执行计划见 [specs/](./specs/)。
