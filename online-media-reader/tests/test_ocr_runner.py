# -*- coding: utf-8 -*-
"""gallery-and-durable-evidence ticket 02：OCR worker 机器结果与日志隔离。

通过真实 ocr_runner.py 子进程边界注入第三方替身：分别在导入、模型构造、
推理迭代与退出期间向 stdout 输出日志，覆盖 Python 层与原生文件描述符写入。
调用方（ocr.py）的严格解析契约不变：整个 stdout 必须是一次完整 JSON。
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
RUNNER = MODULE_DIR / "scripts" / "omr" / "ocr_runner.py"

sys.path.insert(0, str(MODULE_DIR / "scripts"))

STUB_LOG_AT_IMPORT = """
import os, sys
os.write(1, b"downloading model... 40%")
print("Creating model: PP-OCRv5")

class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        return [{"rec_texts": ["机器结果样本文本"]}]

PaddleOCR = _Engine
"""

STUB_LOG_AT_CONSTRUCT = """
import os, sys
def _log():
    print("init logs before engine ready")
    os.write(1, b"warmup native log")

class _Engine:
    def __init__(self, **kwargs):
        _log()
    def predict(self, image):
        return [{"rec_texts": ["机器结果样本文本"]}]

PaddleOCR = _Engine
"""

STUB_LOG_AT_INFER_AND_EXIT = """
import atexit, os, sys
class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        os.write(1, b"inference progress")
        print("inference python log")
        return [{"rec_texts": ["机器结果样本文本"]}]
def _exit_log():
    sys.stdout.write("cleanup log")
    os.write(1, b"cleanup native")
atexit.register(_exit_log)

PaddleOCR = _Engine
"""

STUB_RAISES = """
class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        raise RuntimeError("模型加载失败：权重损坏")

PaddleOCR = _Engine
"""

STUB_HANGS = """
import time

class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        time.sleep(300)

PaddleOCR = _Engine
"""

STUB_EMPTY = """
class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        return [{"rec_texts": []}]

PaddleOCR = _Engine
"""

STUB_REPORT_SIZE = """
from PIL import Image

class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        with Image.open(image) as img:
            return [{"rec_texts": [f"{img.width}x{img.height}"]}]

PaddleOCR = _Engine
"""

STUB_REPORT_PATH = """
class _Engine:
    def __init__(self, **kwargs):
        pass
    def predict(self, image):
        return [{"rec_texts": [str(image)]}]

PaddleOCR = _Engine
"""

ALL_STUBS = (STUB_LOG_AT_IMPORT, STUB_LOG_AT_CONSTRUCT, STUB_LOG_AT_INFER_AND_EXIT)


def _write_stub(base, stub_source):
    stub_dir = base / "paddleocr"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "__init__.py").write_text(textwrap.dedent(stub_source), encoding="utf-8")
    return base


def _write_image(work_root):
    from PIL import Image

    image = work_root / "img.jpg"
    Image.new("RGB", (8, 8), "white").save(image, "JPEG")
    return image


def run_runner(work_root, image, stub_source):
    """以隔离 PYTHONPATH 注入假 paddleocr 模块，运行真实 worker 子进程。"""
    stub_base = _write_stub(work_root / "stub", stub_source)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(stub_base) + ":" + env.get("PYTHONPATH", "")
    env["PADDLE_PDX_CACHE_HOME"] = str(work_root / "models")
    return subprocess.run(
        [sys.executable, str(RUNNER), str(image),
         "--workdir", str(work_root / "work"),
         "--model-cache", str(work_root / "models")],
        capture_output=True, text=True, env=env,
    )


def run_ocr_image(work_root, image, stub_source, timeout_seconds=None):
    """经 ocr.ocr_image 调用方边界运行（PYTHONPATH 注入假 paddleocr）。"""
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import ocr as ocr_module

    stub_base = _write_stub(work_root / "stub-caller", stub_source)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(stub_base) + ":" + env.get("PYTHONPATH", "")
    env["PADDLE_PDX_CACHE_HOME"] = str(work_root / "models-caller")
    original_env = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        kwargs = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return ocr_module.ocr_image(str(image), str(work_root / "w"),
                                    str(work_root / "models-caller"), **kwargs)
    finally:
        os.environ.clear()
        os.environ.update(original_env)


def test_worker_isolates_native_fd_log_at_import(work_root):
    result = run_runner(work_root, _write_image(work_root), STUB_LOG_AT_IMPORT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"text": "机器结果样本文本"}
    assert "downloading model" in result.stderr


def test_worker_isolates_python_and_native_logs_at_construct(work_root):
    result = run_runner(work_root, _write_image(work_root), STUB_LOG_AT_CONSTRUCT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"text": "机器结果样本文本"}
    assert "warmup native log" in result.stderr


def test_worker_isolates_logs_at_infer_and_exit(work_root):
    result = run_runner(work_root, _write_image(work_root), STUB_LOG_AT_INFER_AND_EXIT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"text": "机器结果样本文本"}
    assert "inference progress" in result.stderr
    assert "cleanup log" in result.stderr
    assert "cleanup native" in result.stderr


def test_caller_survives_log_pollution_from_every_phase(work_root):
    image = _write_image(work_root)
    for stub in ALL_STUBS:
        assert run_ocr_image(work_root, image, stub) == "机器结果样本文本"


def test_caller_reports_real_failure_instead_of_empty_text(work_root):
    from omr.model import OMRError

    try:
        run_ocr_image(work_root, _write_image(work_root), STUB_RAISES)
    except OMRError as exc:
        assert "模型加载失败" in str(exc)
    else:
        raise AssertionError("真实识别失败必须报错，不得当作空文字")


def test_caller_times_out_hung_worker_with_locatable_image(work_root):
    from omr.model import OMRError

    image = _write_image(work_root)
    try:
        run_ocr_image(work_root, image, STUB_HANGS, timeout_seconds=1)
    except OMRError as exc:
        message = str(exc)
        assert "未返回" in message
        assert "img.jpg" in message
    else:
        raise AssertionError("挂死的 OCR worker 必须超时报错，不得无限等待")


def test_caller_empty_result_maps_to_none(work_root):
    assert run_ocr_image(work_root, _write_image(work_root), STUB_EMPTY) is None


def test_worker_result_channel_carries_single_json(work_root):
    result = run_runner(work_root, _write_image(work_root), STUB_LOG_AT_IMPORT)
    assert result.stdout.count("机器结果样本文本") == 1
    assert result.stdout.startswith('{"text"')


def test_worker_downscales_oversized_input_before_predict(work_root):
    from PIL import Image

    big = work_root / "big.png"
    Image.new("RGB", (1600, 1600), "white").save(big, "PNG")
    result = run_runner(work_root, big, STUB_REPORT_SIZE)
    assert result.returncode == 0, result.stderr
    width, height = json.loads(result.stdout)["text"].split("x")
    assert int(width) * int(height) <= 1_600_000
    assert (int(width), int(height)) != (1600, 1600)


def test_worker_passes_small_supported_input_through(work_root):
    from PIL import Image

    small = work_root / "small.png"
    Image.new("RGB", (800, 600), "white").save(small, "PNG")
    result = run_runner(work_root, small, STUB_REPORT_PATH)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["text"] == str(small)
