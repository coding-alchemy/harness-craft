---
name: online-media-reader
description: 从抖音、B站或小红书的公开单条链接读取文字内容（有界探测可靠字幕，否则下载转写；小红书图片 OCR），生成标明来源的 Markdown。用户给出这三类平台的链接并想阅读其文字内容时使用，包括"读取这个视频的字幕/文字/内容""转写这个链接""OCR 这组小红书图片"等表述。
---

# 在线媒体文字读取

把一个受支持平台的公开单条链接转成可核对的 Markdown。

## 调用入口

```bash
python3 <SKILL目录>/scripts/read.py <URL> [--output <输出.md>] [--keep-media] [--verify-audio] [--whisper-model <模型>]
python3 <SKILL目录>/scripts/read.py <URL> --probe-only
python3 <SKILL目录>/scripts/review.py <run_dir> --corrections <corrections.json>
```

`<SKILL目录>` 是本 `SKILL.md` 所在目录。保持命令的 cwd 为用户当前执行目录，不要先切换到 Skill 目录。平台识别、字幕探测、下载、转写、OCR 和清理全部由脚本完成。普通运行默认把结果写入命令启动目录的 `.media/<平台>-<内容ID>-<时间>/content.md`；读取 stdout JSON 的 `result_path` 取得唯一正文，`run_dir/manifest.json` 用于定位和诊断。视频正文先给"完整连续字幕"（无时间戳），随后是同一主轨渲染的带时间戳字幕；图文 OCR 只有逐图小节。`--output` 仅在用户明确指定其他结果路径时使用。

只需确认能否在线取得字幕时使用 `--probe-only`，读取其 JSON；该模式会在需要时走与普通运行相同的匿名浏览器取数路径，但不下载媒体或运行 ASR。不要在 Skill 层另行浏览页面或重写平台逻辑。

## ASR 画面复核

stdout 返回 `review_required: true` 时，正文是尚未校对的原始 ASR；完成下列复核并取得终态后才能向用户交付"校对版"：

1. 读取 `review_path` 下 `input.json` 的全部 cue，逐个查看登记的证据帧（路径相对 `run_dir`）。每个 cue 都必须检查；不要自行推算时间或另行取帧。
2. 只有画面中可见的文字才能纠正：产品名、专有名词、数字和画面逐字字幕。每条纠正包含 cue 编号、替换后的完整 cue 文字和至少一个属于该 cue 的证据帧路径。普通画面文案不能补写成语音内容。
3. 画面无文字、不可读或与语音可能不同的 cue 保留原文；可以标记待听校，但不得凭领域知识改写，也不得声称已回听音频。
4. 把结构化纠正写入 JSON 文件后调用复核入口；脚本校验全部 cue 已检查、替换完整且证据归属正确，然后原子重渲染唯一正文（连续全文与时间戳同步更新）：

   ```json
   {"reviewed_cue_ids": [1, 2], "corrections": [{"cue_id": 1, "text": "画面读到的完整文字", "evidence_frames": ["review/frames/cue-0001-p50.jpg"]}]}
   ```

   零纠正时提交空 `corrections` 列表。环境无法查看本地图片时提交 `{"result": "unavailable", "reason": "原因"}`，保留原始 ASR 并如实告知用户未完成画面复核。
5. 以复核入口 stdout 的 `review_status` 为准：`reviewed` 或 `unavailable` 才是终态。校验失败时脚本整体拒绝且不改正文，修正后重新提交即可；复核成功后不接受重复提交。

## 自适应决策顺序

脚本按以下顺序决定文字来源，输出中的"处理路径"字段标明实际来源：

1. 视频以 ASR 为稳定默认路径，同时给平台字幕探测最多 30 秒总预算。脚本只验证最高优先级的一轨：中文人工字幕 → 中文自动字幕 → 平台默认人工字幕 → 平台默认自动字幕。
2. 字幕已下载且质量可靠时直接采用，不下载媒体、不转写；仅使用 `--keep-media` 时下载媒体但仍不转写。
3. 字幕缺失、不可访问、无效、明显不完整、探测超时或与页面信息冲突时，脚本立即下载媒体并用 faster-whisper 转写。中文内容自动把标题和作者作为识别提示。用户要求原音核验时传入 `--verify-audio`，把可靠字幕作为主正文并附上 ASR 核验结果。默认模型为 small，可用 `--whisper-model` 指定。ASR 成为主文字源时脚本自动生成画面复核材料并置 `review_required: true`。
4. 小红书图文按页面顺序逐图 OCR；每张图片一个独立小节，无文字时写明"未识别到文字"。
5. 平台 AI 摘要只作为补充信息输出，不替代字幕或转写。

## 停止条件

字幕探测由脚本确定性完成；一次瞬时网络故障可在 30 秒剩余预算内重试。探测失败后直接采用脚本给出的 ASR 决策。内容本身遇到登录墙、验证码、私密、地区限制或依赖缺失（yt-dlp、ffmpeg、faster-whisper、PaddleOCR）时，读取 stderr JSON，报告 `stage`、`error` 和 `run_dir`。

成功后删除 `work/`；ASR 复核材料（`review/` 的原始 cue、证据帧和纠正记录）随结果保留；复核所需的临时视频在取帧后删除。失败保留其中的非 Cookie 材料供诊断。`--keep-media` 只在完整下载并原子发布后生成 `run_dir/artifacts/source.<ext>`，永不保留 Cookie。Whisper 与 PaddleOCR 模型固定落在执行目录 `.media/tools/`，图片格式转换位于本次 `work/`。脚本不自动安装依赖；确需安装时先取得用户授权，不默认写入全局目录。
