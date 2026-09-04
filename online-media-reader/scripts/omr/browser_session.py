# -*- coding: utf-8 -*-
"""匿名浏览器会话：独立临时上下文，不读取日常浏览器资料。

Cookie 写入工作区外临时文件（Netscape 格式，仅当前用户可读），
供 yt-dlp 使用，随工作目录清理一并删除。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

from .model import OMRError

NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# 由 online-media-reader 匿名会话生成，用后即删\n"
BROWSER_RUNNER = Path(__file__).resolve().parent / "browser_runner.py"


def write_cookie_jar(cookies, path):
    """把 Cookie 列表写成 Netscape 格式，权限 0600。"""
    lines = [NETSCAPE_HEADER]
    for c in cookies:
        domain = c.get("domain", "")
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expires", 0) or 0)
        lines.append(
            f"{domain}\t{include_sub}\t{c.get('path', '/')}\t{secure}\t{expiry}\t"
            f"{c['name']}\t{c['value']}\n"
        )
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8", closefd=True) as cookie_file:
        os.fchmod(cookie_file.fileno(), 0o600)
        cookie_file.write("".join(lines))
    return path


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise OMRError(
            "缺少 playwright 浏览器能力，无法建立匿名会话。请安装 playwright 及其浏览器。",
            exit_code=3,
        )
    return sync_playwright().start()


def _collect_cookies(url, timeout_ms=30000):
    """在 runner 进程内启动匿名浏览器并返回 Cookie 列表。"""
    deadline = monotonic() + timeout_ms / 1000

    def remaining_ms():
        remaining = int(round((deadline - monotonic()) * 1000))
        if remaining <= 0:
            raise TimeoutError("匿名浏览器访问超过共享字幕探测预算")
        return remaining

    pw = _chromium()
    try:
        try:
            browser = pw.chromium.launch(headless=True, timeout=remaining_ms())
            try:
                context = browser.new_context()  # 全新匿名上下文，无日常资料
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=remaining_ms(),
                )
                cookies = context.cookies()
            finally:
                browser.close()
        except Exception as exc:
            raise OMRError(f"匿名浏览器访问失败：{exc}", exit_code=4) from None
    finally:
        pw.stop()
    return cookies


def _collect_state(url, extract_expr, timeout_ms=50000):
    """在 runner 进程内匿名渲染页面并返回可 JSON 化状态。"""
    deadline = monotonic() + timeout_ms / 1000

    def remaining_ms():
        remaining = int(round((deadline - monotonic()) * 1000))
        if remaining <= 0:
            raise TimeoutError("匿名浏览器渲染超过预算")
        return remaining

    pw = _chromium()
    try:
        try:
            browser = pw.chromium.launch(headless=True, timeout=remaining_ms())
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=remaining_ms(),
                )
                page.wait_for_timeout(min(5000, remaining_ms()))
                return page.evaluate(extract_expr)
            finally:
                browser.close()
        except Exception as exc:
            raise OMRError(f"匿名浏览器渲染失败：{exc}", exit_code=4) from None
    finally:
        pw.stop()


def _run_browser(mode, url, timeout_ms, extract_expr=None):
    argv = [
        sys.executable,
        str(BROWSER_RUNNER),
        mode,
        url,
        str(timeout_ms),
    ]
    try:
        result = subprocess.run(
            argv,
            input=extract_expr,
            capture_output=True,
            text=True,
            timeout=max(timeout_ms / 1000, 0.001),
        )
    except subprocess.TimeoutExpired:
        seconds = max(1, int(round(timeout_ms / 1000)))
        message = (
            "匿名浏览器访问超过共享字幕探测预算"
            if mode == "cookies"
            else f"浏览器渲染超过 {seconds} 秒预算"
        )
        raise OMRError(message, exit_code=4) from None

    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise OMRError("匿名浏览器返回数据无法解析。", exit_code=4) from None
    if result.returncode != 0:
        raise OMRError(
            payload.get("error") or "匿名浏览器访问失败。",
            exit_code=int(payload.get("exit_code", 4)),
        )
    return payload


def anonymous_cookie_jar(url, workdir, timeout_ms=30000):
    """在硬墙钟预算内运行独立浏览器进程并落私有 Cookie 文件。"""
    payload = _run_browser("cookies", url, timeout_ms)
    return write_cookie_jar(payload.get("cookies") or [], workdir / "cookies.txt")


def render_state(url, extract_expr, timeout_ms=50000):
    """在硬墙钟预算内匿名渲染页面并执行提取表达式。"""
    return _run_browser("state", url, timeout_ms, extract_expr).get("state")
