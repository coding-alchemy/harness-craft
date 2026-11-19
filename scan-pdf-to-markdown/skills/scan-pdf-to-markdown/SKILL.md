---
name: scan-pdf-to-markdown
description: 将本地扫描或混合 PDF 转为可逐块回查原页的 Markdown，保留配图、表格和识别疑点。用户要求转换扫描件、核验阅读包、核实原页并更正或免 OCR 重建时使用。
---

# 扫描 PDF 转可回源 Markdown

从本 `SKILL.md` 所在目录解析 `scripts/scan_pdf.py`，用该脚本处理用户给出的本地 PDF。发布目录必须是新目录。用户省略输出位置时，在源件旁选择尚未占用的 `<文件名>-markdown` 目录或其编号后缀。

- **转换整本**　使用版本符合 `requirements-ocr.txt` 且可读取本地 MinerU Basic 权重的 Python 运行 `scan_pdf.py parse PDF --output 新目录`。新会话默认使用安装说明中的 ONNX/CPU；沿用调用者在环境或 MinerU 配置文件中的显式选择。按 CLI 诊断处理缺少的依赖或模型。
- **重建**　使用装有 `requirements.txt` 的 Python 运行 `scan_pdf.py render 结果目录 --source-pdf 同一PDF --output 新目录`。原件和 `raw/` 足以重建，已有 `review.json` 随包回放。
- **核验**　用读取环境运行 `scan_pdf.py verify 结果目录 --source-pdf 同一PDF`，以本次命令的结论和位置诊断为准。

在回复中写明命令的结论（通过、降级或失败）。成功交付 `document.md` 和 `qa-report.md` 的位置，按报告指出待核对的物理页与块。配图随完整目录移动。失败时返回原因与诊断路径。整本未识别出可读内容时，保留命令交付的候选目录供后续原页复核。

**查证或更正**　按 [原页复核与更正](references/review.md) 从块标识定位物理页、查看原图、准备完整复核记录，并从原始包重建到新目录。仅把实际核实的内容写入确认或更正项，看不清的内容保留为存疑。
