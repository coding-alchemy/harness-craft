# 在线媒体文字读取（online-media-reader）

本模块提供一个可安装的 Agent Skill，唯一 Skill 源目录为 [skills/online-media-reader/](./skills/online-media-reader/)：入口 [SKILL.md](./skills/online-media-reader/SKILL.md)、主读取 [scripts/read.py](./skills/online-media-reader/scripts/read.py)、ASR 画面复核 [scripts/review.py](./skills/online-media-reader/scripts/review.py) 与条件依赖声明 [requirements.txt](./skills/online-media-reader/requirements.txt) 都在该目录内，随 Skill 整体安装。README、规格、架构图、测试和安装器留在模块根目录，不属于安装包。它从抖音、B站和小红书的公开单条链接自适应取得文字内容，输出标明来源的 Markdown。

## 安装

```bash
# Codex：安装/更新到 ${CODEX_HOME:-~/.codex}/skills/online-media-reader
python3 online-media-reader/install_skill.py
# 受管文件冲突时默认拒绝；确认替换后使用：
python3 online-media-reader/install_skill.py --force
```

安装器只依赖 Python 标准库，把 Skill 源目录的全部发布文件复制到 `${CODEX_HOME:-~/.codex}/skills/online-media-reader`；相同内容与权限的重复安装成功且不重写文件，目标中的未知文件保留，不创建依赖、模型、浏览器、配置或凭据。其他兼容 Agent Skills 的工具可直接把整个 `skills/online-media-reader/` 复制到目标 Skill 根目录（不要只复制 `SKILL.md`）。

安装后从安装目录内的 [requirements.txt](./skills/online-media-reader/requirements.txt) 按实际使用的处理分支显式安装依赖，例如：

```bash
pip install -r "${CODEX_HOME:-$HOME/.codex}/skills/online-media-reader/requirements.txt"
```

条件依赖清单见下文"条件依赖"。

## 使用

`<SKILL目录>` 指已安装或已复制的 `online-media-reader` Skill 目录（源码内即 `online-media-reader/skills/online-media-reader`）：

```bash
python3 <SKILL目录>/scripts/read.py <URL> [--output 结果.md] [--keep-media] [--verify-audio] [--whisper-model small]
python3 <SKILL目录>/scripts/read.py <URL> --probe-only
python3 <SKILL目录>/scripts/review.py <run_dir> --corrections <corrections.json>
```

处理路径自适应：脚本在 30 秒总预算内只验证最高优先级的平台字幕（人工 > 自动，中文优先），可靠时直接采用；字幕缺失、不可访问、无效或超时则下载媒体并用 faster-whisper 转写。中文转写会使用标题和作者作为短提示。`--probe-only` 只输出机器可读的字幕可用性决策，不下载媒体或运行 ASR；`--verify-audio` 可在字幕可靠时附加 ASR 核验。小红书与抖音图文按页面原始顺序逐图 PaddleOCR（抖音支持 `/note/<id>` 详情、官方短链与 `modal_id` 入口，图文不进入视频下载或 ASR）；平台 AI 摘要只作为补充，不替代正文。

脚本交付的基础视频报告依次是原始字幕（与主字幕轨同源渲染的连续全文，无时间戳）和带时间戳字幕；Agent 在交付前依据原始字幕完成三项阅读整理——完整字幕（补齐标点、断句与段落）、完整版内容（覆盖全部实质信息的完整文章）和一句话概括，并按"来源信息及处理说明 → 一句话概括 → 完整版内容 → 完整字幕 → 原始字幕 → 分时间字幕"写回同一 `result_path`，平台摘要如有仍在字幕之后。复核纠正后各层同步更新，不存在两份独立文本。ASR 成为主文字源时，主入口为每个非空 cue 提取有界画面证据帧并返回 `review_required: true`；复核入口校验结构化纠正（全部 cue 已检查、完整替换、证据帧归属正确）后原子重渲染唯一正文。无视觉能力时提交显式 `unavailable`，保留原始 ASR 并如实记录未完成画面复核。

普通运行默认在命令启动目录生成：

```text
.media/<平台>-<内容ID>-<时间>/
├── content.md
├── manifest.json              # 含 evidence_path 指向证据入口
├── evidence/
│   ├── index.json             # 证据入口：正文位置与材料清单
│   ├── subtitle-cues.json     # 可靠字幕运行的 cue 白名单快照
│   ├── ocr-snapshot.json      # 图文运行的逐图 OCR 原始识别结果
│   ├── images/                # 图文运行的逐图原图
│   └── verification.md        # Agent 整理核对记录（交付时写入）
├── review/                    # 仅 ASR 主路径
│   ├── input.json             # 原始 cue 与证据映射
│   ├── corrections.json       # 复核入口保存的纠正记录
│   └── frames/                # 每个 cue 最多三张证据帧
└── artifacts/source.<ext>     # 仅 --keep-media
```

持久结果与证据禁止写入 `/tmp` 等系统临时目录：从临时目录（含符号链接落入）启动命令或把 `--output` 指向临时位置时明确报错，不生成正式结果。成功清理 `work/` 不影响 `evidence/`；OCR 原图默认保留，不依赖 `--keep-media`。

stdout JSON 的 `result_path` 指向唯一正文，`run_dir` 指向本次运行目录；待复核的 ASR 运行同时返回 `review_required: true` 和 `review_path`，复核入口完成后 stdout 与 `manifest.json` 的 `review_status` 给出终态。成功后中间目录 `work/` 被删除，`review/` 随结果保留，复核临时视频在取帧后删除；失败时 stderr JSON 返回失败 `stage`、`error` 和 `run_dir`，并保留非 Cookie 中间材料。Ctrl-C 同样返回结构化错误并删除 Cookie。`--output` 是显式兼容覆盖，不会额外生成 `content.md`；正文和 `--keep-media` 媒体只有在原子发布成功后才成为正式结果。

遇到登录墙、验证码、私密内容或依赖缺失时报错并指出失败阶段，不自动登录或绕过限制。OCR worker 每张图限时 600 秒，超时或失败按编号明确报错；面积超过上限（约 160 万像素）的图片在识别前等比缩小，规避 paddle 3.0 在 macOS x86_64 上对大图输入的段错误。

## 条件依赖

脚本不自动安装依赖。按实际使用的处理分支配置（[requirements.txt](./skills/online-media-reader/requirements.txt)）：

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

全部测试使用固定样本与假外部命令（临时 PATH 与 `OMR_WHISPER_BIN` / `OMR_OCR_BIN`），不访问真实网络；其中 `tests/test_online_media_reader_installer.py` 覆盖安装器合同与脱离源码启动验收（共享合同实现见仓库根 [tests/installer_contract.py](../tests/installer_contract.py)）。规格与执行计划见 [specs/](./specs/)。
