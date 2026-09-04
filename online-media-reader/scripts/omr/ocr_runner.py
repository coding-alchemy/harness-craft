#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PaddleOCR worker：image_path → stdout 输出 {"text": "..."}。"""

import argparse
import json
import os
import sys
from pathlib import Path


def _to_supported(path: str, workdir: str) -> str:
    """PaddleOCR 只认 jpg/png/jpeg/bmp/pdf；webp 等先经 PIL 转换。"""
    if Path(path).suffix.lower().lstrip(".") in ("jpg", "png", "jpeg", "bmp", "pdf"):
        return path
    from PIL import Image

    with Image.open(path) as img:
        dest = Path(workdir) / (Path(path).stem + ".jpg")
        img.convert("RGB").save(dest, "JPEG")
    return str(dest)


def main():
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
    json.dump({"text": "\n".join(lines)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
