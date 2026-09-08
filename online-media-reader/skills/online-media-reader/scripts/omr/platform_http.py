# -*- coding: utf-8 -*-
"""三个平台适配器共用的 HTTP 访问与错误报告工具。"""

import json
import math
import re
import shutil
import subprocess
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .model import AccessRestrictedError, OMRError

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def make_opener():
    opener = build_opener()
    opener.addheaders = [("User-Agent", UA)]
    return opener


def request(url):
    return Request(url, headers={"User-Agent": UA})


def _set_response_timeout(response, timeout):
    """把当前剩余时间下推到底层 socket；测试替身可以没有 socket。"""
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    for candidate in (sock, raw, fp):
        setter = getattr(candidate, "settimeout", None)
        if setter:
            setter(max(timeout, 0.001))
            return


def _read_text_until(response, deadline, timeout, url):
    """分块读取响应，并在每次底层读取前重新应用绝对截止时间。"""
    read1 = getattr(response, "read1", None)
    if read1 is None:
        data = response.read()
        if monotonic() > deadline:
            raise TimeoutError(f"页面访问超过 {math.ceil(timeout)} 秒：{url}")
        return data.decode("utf-8", "replace")

    chunks = []
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(f"页面访问超过 {math.ceil(timeout)} 秒：{url}")
        _set_response_timeout(response, remaining)
        chunk = read1(64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


def open_text(opener, req, timeout, started=None):
    """在一个墙钟截止时间内完成打开与正文读取。"""
    started = monotonic() if started is None else started
    deadline = started + timeout
    with opener.open(req, timeout=timeout) as response:
        return _read_text_until(
            response, deadline, timeout, getattr(req, "full_url", str(req))
        )


def fetch_text(url, ua=None, referer=None, timeout=30):
    """取 URL 文本。B站等按 TLS 指纹拦截 Python 客户端（412）时退回 curl。"""
    started = monotonic()
    headers = {"User-Agent": ua or UA}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    try:
        return open_text(build_opener(), req, timeout, started=started)
    except HTTPError as exc:
        if exc.code != 412:
            raise
        remaining = timeout - (monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(f"页面访问超过 {math.ceil(timeout)} 秒：{url}")
        return _curl_text(url, headers, remaining)


def _curl_text(url, headers, timeout):
    if shutil.which("curl") is None:
        raise OMRError(
            "平台接口拒绝了 Python 客户端（HTTP 412），需要 curl 作为备用 HTTP 通道。"
            "请安装 curl 后重试。", exit_code=3,
        )
    max_time = max(timeout, 0.001)
    argv = ["curl", "-sL", "--max-time", f"{max_time:.3f}", url]
    for key, value in headers.items():
        argv += ["-H", f"{key}: {value}"]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=max_time
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"页面访问超过 {math.ceil(max_time)} 秒：{url}") from exc
    if result.returncode == 28:
        raise TimeoutError(f"页面访问超过 {math.ceil(max_time)} 秒：{url}")
    if result.returncode != 0:
        raise OMRError(f"页面访问失败（curl 退出码 {result.returncode}）：{url}", exit_code=4)
    return result.stdout


def fail_closed(markers, html, platform):
    """页面包含限制标记时立即失败，不重试、不绕过。"""
    for marker in markers:
        if marker in html:
            raise AccessRestrictedError(
                f"{platform}页面要求：{marker}。受限制内容不支持自动处理，已停止。",
                exit_code=4,
            )


def parse_embedded_json(html, pattern, what):
    """从页面提取嵌入 JSON；解析失败时明确报告，不产生貌似完整的结果。"""
    m = re.search(pattern, html, re.S)
    if not m:
        raise OMRError(f"无法从{what}提取数据，页面结构可能已变化。", exit_code=4)
    try:
        return json.loads(m.group(1))
    except ValueError:
        raise OMRError(f"{what}数据解析失败，页面结构可能已变化。", exit_code=4)


def last_error_line(stderr):
    lines = (stderr or "").strip().splitlines()
    return lines[-1] if lines else "未知错误"
