#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PaddleOCR worker：image_path → stdout 输出 {"text": "..."}。

结果通道与日志隔离：本模块在导入任何第三方库之前先保存原始 stdout 作为
唯一结果通道，再把文件描述符 1 与 Python 层标准输出转向 stderr——第三方
在导入、模型构造、推理与退出期间的日志（含原生 fd 直写与缓冲）只能进入
stderr，stdout 自始至终只承载最终一次完整 JSON。
"""

import argparse
import json
import os
import sys
from pathlib import Path


# paddle 3.0 在 macOS x86_64 上对大面积输入会段错误并卡死在自带崩溃
# 处理器（真实样本 1440×1440 复现，1200×1200 与 1080×1370 正常），
# 超限图片等比缩到面积上限内再推理。
_MAX_AREA = 1_600_000


def _to_supported(path: str, workdir: str) -> str:
    """PaddleOCR 只认 jpg/png/jpeg/bmp/pdf；webp 等先经 PIL 转换。"""
    from PIL import Image

    src = Path(path)
    with Image.open(src) as img:
        oversized = img.width * img.height > _MAX_AREA
        supported = src.suffix.lower().lstrip(".") in ("jpg", "png", "jpeg", "bmp", "pdf")
        if supported and not oversized:
            return path
        dest = Path(workdir) / (src.stem + ".jpg")
        converted = img.convert("RGB")
        if oversized:
            scale = (_MAX_AREA / (img.width * img.height)) ** 0.5
            converted = converted.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.LANCZOS,
            )
        converted.save(dest, "JPEG")
    return str(dest)


def _isolate_result_channel():
    """保存 fd1 副本作结果通道；fd1 与 Python stdout 一并转向 stderr。"""
    stream = os.fdopen(os.dup(1), "w", encoding="utf-8")
    sys.stderr.flush()
    os.dup2(2, 1)
    sys.stdout = os.fdopen(1, "w", encoding="utf-8", closefd=False)
    return stream


def main():
    result_stream = _isolate_result_channel()
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--model-cache", required=True)
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    model_cache = Path(args.model_cache).resolve()
    model_cache.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(model_cache)

    from paddleocr import PaddleOCR

    engine = PaddleOCR(
        lang="ch",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    result = list(engine.predict(_to_supported(args.image_path, str(workdir))) or [])
    lines = []
    for res in result or []:
        lines.extend(res.get("rec_texts") or [])
    payload = json.dumps({"text": "\n".join(lines)}, ensure_ascii=False)
    result_stream.write(payload)
    result_stream.flush()


if __name__ == "__main__":
    main()
