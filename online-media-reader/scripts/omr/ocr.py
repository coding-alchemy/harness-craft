# -*- coding: utf-8 -*-
"""PaddleOCR 图片文字识别处理器（唯一 OCR 后端，简体中文模型）。

经 argv 调用独立 runner，便于测试用假命令替换（OMR_OCR_BIN）。
只识别文字，不生成画面描述。
"""

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from .model import OMRError
from .platform_http import last_error_line

OCR_RUNNER = Path(__file__).resolve().parent / "ocr_runner.py"


def require_ocr():
    if "paddleocr" not in sys.modules and importlib.util.find_spec("paddleocr") is None:
        raise OMRError(
            "缺少 PaddleOCR，无法识别图片文字。请安装 paddleocr 后重试。", exit_code=3
        )


def ocr_image(image_path, workdir, model_cache):
    """识别单张图片，返回文本；无文字时返回 None。"""
    ocr_bin = os.environ.get("OMR_OCR_BIN")
    if ocr_bin:
        argv = [ocr_bin, str(image_path)]
    else:
        require_ocr()
        argv = [sys.executable, str(OCR_RUNNER), str(image_path)]
    argv += ["--workdir", str(workdir), "--model-cache", str(model_cache)]
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise OMRError(
            f"图片 OCR 失败：{last_error_line(result.stderr)}"
        )
    try:
        text = json.loads(result.stdout).get("text", "")
    except json.JSONDecodeError:
        raise OMRError("图片 OCR 失败：输出无法解析。")
    return text.strip() or None
