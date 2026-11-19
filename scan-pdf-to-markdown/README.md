# 扫描 PDF 转可回源 Markdown

**把 MinerU 的一次识别结果，变成日后能查证、能更正、能重新生成的阅读包。** MinerU 负责 OCR。`document.md` 和配图可以直接阅读，也可以交给模型按原句引用、按表头读数。遇到疑点，从正文的块 ID 查回原 PDF 的物理页和原始识别记录。

## 项目介绍

16 行的 `SKILL.md` 告诉 Agent 何时调用哪个命令。Agent 与命令行共用随包的五个 Python 脚本。[Skill 入口](./skills/scan-pdf-to-markdown/SKILL.md) · [初版架构与流程图（42c835e）](./docs/architecture.md)

| 脚本 | 职责 |
| --- | --- |
| [capture.py](./skills/scan-pdf-to-markdown/scripts/capture.py) | 调用 MinerU，保留原始识别 ZIP，记录源 PDF 的指纹、页数、裁切框和旋转角。重建时据此检查是否为同一份原件。 |
| [reading.py](./skills/scan-pdf-to-markdown/scripts/reading.py) | 组织 Markdown 与配图，处理表格、上下标、续段和疑点。为段落、表格和图片分配块 ID，并关联原页、坐标和原始识别记录。 |
| [review.py](./skills/scan-pdf-to-markdown/scripts/review.py) | 按块或单元格应用人工更正。已核对的内容发生变化时标记待复核，并把复核结论和更正写入质量报告。 |
| [verify.py](./skills/scan-pdf-to-markdown/scripts/verify.py) | 重算预期结果，对照磁盘上的正文、来源映射、配图和报告。移走一张配图时，定位缺失的文件。 |
| [scan_pdf.py](./skills/scan-pdf-to-markdown/scripts/scan_pdf.py) | 提供 `parse`、`render` 和 `verify`。转换或重建先在候选目录生成并核验，再以排他重命名发布到新目标，保护已有结果。 |

例如，MinerU 把表格里的一格读成 `18`。你看原页确认是 `13`，便可记录物理页、表格块 ID、行列和更正依据。以后用 `render` 免 OCR 重建时，原始识别记录仍是 `18`，Markdown 显示 `13`，质量报告说明哪一格改了以及为什么。[单格更正示例](./skills/scan-pdf-to-markdown/references/review.md#一格更正示例)

只做一次性阅读时，取 `document.md` 和配图即可。需要日后核对或更新正文时，保留完整阅读包和源 PDF。项目测试覆盖旋转页回源、单格更正、图片损坏和并发发布。开发需求、设计和执行计划见 [规格目录](./specs/)。

## 安装

把 [完整 Skill 目录](./skills/scan-pdf-to-markdown/) 复制到 Agent 工具的 Skill 根目录。例如从仓库根目录安装到 Codex 的个人目录，请使用尚未占用的目标路径。

```sh
skills_root="${CODEX_HOME:-$HOME/.codex}/skills"
skill_dir="$skills_root/scan-pdf-to-markdown"
mkdir -p "$skills_root"
test ! -e "$skill_dir" && cp -R scan-pdf-to-markdown/skills/scan-pdf-to-markdown "$skill_dir"
```

用虚拟环境安装相应依赖。首版在 macOS、Python 3.12、MinerU 4.1.7 Basic 与 ONNX CPU 上验收。读取环境只需 [requirements.txt](./skills/scan-pdf-to-markdown/requirements.txt)。首次 OCR 使用 [requirements-ocr.txt](./skills/scan-pdf-to-markdown/requirements-ocr.txt) 和已下载的本地权重。

```sh
python3.12 -m venv .scan-reader
.scan-reader/bin/python -m pip install -r "$skill_dir/requirements.txt"
python3.12 -m venv .scan-ocr
.scan-ocr/bin/python -m pip install -r "$skill_dir/requirements-ocr.txt"
.scan-ocr/bin/mineru-kit models download --tier basic --small-backend onnx --source modelscope
.scan-ocr/bin/mineru-kit models verify --tier basic --small-backend onnx
```

`parse` 使用本地模型。CLI 和 Agent 在新会话中默认使用 ONNX/CPU。后端和设备分别沿用调用者的环境变量或 MinerU 配置文件（含 `MINERU_CONFIG` 指定的文件），环境变量优先。模型修订和依赖基线见 `requirements-ocr.txt`。发布使用 macOS 的排他目录重命名，文件系统需要支持该操作。

## 使用

```sh
.scan-ocr/bin/python "$skill_dir/scripts/scan_pdf.py" parse 扫描件.pdf --output 初次结果
.scan-reader/bin/python "$skill_dir/scripts/scan_pdf.py" render 初次结果 --source-pdf 扫描件.pdf --output 重建结果
.scan-reader/bin/python "$skill_dir/scripts/scan_pdf.py" verify 重建结果 --source-pdf 扫描件.pdf
```

也可以向已安装的 Skill 说“把这份扫描件转成 Markdown，保留配图，告诉我哪里需要核对”。新目录内的 `document.md` 使用相对路径引用 `assets/`。`blocks.jsonl`、`source-map.json` 和 `raw/` 供回源与重建，`qa-report.md` 记录机器检查和原页复核。保留完整目录和同一份源 PDF，可在无 OCR 环境重建。`render` 默认沿用随包的 `review.json`，也支持通过 `--review 文件` 提供新一版完整记录。字段和更正步骤见 [原页复核](./skills/scan-pdf-to-markdown/references/review.md)。

通过和降级返回 0。降级报告指出仍需核对的页或块。失败返回 1 并给出具体原因。若整本没有可读正文且空白待确认，命令会给出诊断候选目录，原页复核后可从该目录重建。

## 测试

从仓库根目录用读取环境运行 `python3 -B -m unittest discover -s scan-pdf-to-markdown/tests -v`。真实样张、验收证据和识别产物存放在仓库外。
