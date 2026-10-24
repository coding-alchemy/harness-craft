"""PDF 实际消费者的依赖诊断；不安装、不维护另一份版本清单。"""
import importlib
import shlex
import sys
from pathlib import Path


class PdfDependencyError(ImportError):
    pass


def dependency_message(component, detail='', requirements='requirements-pdf.txt'):
    requirement = Path(__file__).resolve().parent.parent / requirements
    return ('缺少或无法使用当前模式依赖 %s%s\n运行解释器：%s\n'
            '在独立 venv 中用目标解释器安装：<venv>/bin/python -m pip install -r %s'
            % (component, '：' + detail if detail else '', sys.executable,
               shlex.quote(str(requirement))))


def require_module(name, requirements='requirements-pdf.txt'):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise PdfDependencyError(dependency_message(name, str(exc), requirements)) from exc


def preflight_browser():
    """使用当前实际 headless 选择，兼容完整 Chromium 和 only-shell。"""
    runtime = require_module('playwright.sync_api')
    try:
        with runtime.sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except Exception as exc:
        raise PdfDependencyError(dependency_message('Chromium', str(exc))
            + '\n准备浏览器：<venv>/bin/python -m playwright install chromium') from exc
