# -*- coding: utf-8 -*-
"""媒体下载、音频提取与转写的外部命令边界。

所有外部进程都经 argv 独立调用，便于测试用假可执行文件替换
（PATH 中的 yt-dlp / ffmpeg，以及 OMR_WHISPER_BIN 指向的转写命令）。
"""

import json
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from .model import OMRError
from .platform_http import UA_DESKTOP, last_error_line

WHISPER_RUNNER = Path(__file__).resolve().parent / "whisper_runner.py"


def download_direct(url, dest, referer=None):
    """直连下载经页面验证的媒体地址（平台 CDN 通常不拦截普通客户端）。"""
    headers = {"User-Agent": UA_DESKTOP}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except OSError as exc:
        raise OMRError(f"媒体直连下载失败：{exc}")
    if not dest.exists() or dest.stat().st_size == 0:
        raise OMRError("媒体直连下载失败：未产出媒体文件。")


def mux_av(video_path, audio_path, dest):
    """合并视频流与音频流（B站 dash 的 video 流无音轨）。"""
    require_binary("ffmpeg", "合并音视频")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
         "-c", "copy", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise OMRError("ffmpeg 音视频合并失败。")


def download_image(url, dest):
    """下载图片到 dest（支持 http(s) 与 file://）。"""
    try:
        with urlopen(url, timeout=30) as resp, open(dest, "wb") as f:
            f.write(resp.read())
    except (OSError, ValueError) as exc:
        raise OMRError(f"图片下载失败：{exc}", exit_code=4) from None
    if not dest.exists() or dest.stat().st_size == 0:
        raise OMRError(f"图片下载失败：未取得图片数据：{url}", exit_code=4)


def require_binary(name, capability):
    if shutil.which(name) is None:
        raise OMRError(
            f"缺少 {name}，无法{capability}。请安装后重试。", exit_code=3
        )


def cleanup_download_parts(dest):
    """删除 yt-dlp 为当前目标生成的精确或分流 `.part`/`.ytdl` 文件。"""
    prefix = dest.stem + "."
    for path in dest.parent.iterdir():
        if not path.name.startswith(prefix):
            continue
        if ".part" in path.name or path.suffix == ".ytdl":
            path.unlink(missing_ok=True)


def download_media(url, dest, mode, cookies=None):
    """下载媒体。mode: 'audio'（转写用）、'best'（保留用）或 'review'（复核低清视频）。

    cookies 为 Netscape 文件。部分平台（小红书）只提供合成流，无纯音频格式时
    回退到最佳合成流，后续 ffmpeg 提取仍可得到音频。
    """
    require_binary("yt-dlp", "下载媒体")
    fmt = {
        "audio": "bestaudio/best",
        "best": "bv*+ba/b",
        "review": "bv[height<=480]/b[height<=480]/wv/w",
    }[mode]
    argv = ["yt-dlp", "-f", fmt, "-o", str(dest)]
    if cookies:
        argv += ["--cookies", str(cookies)]
    argv.append(url)
    try:
        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode != 0:
            raise OMRError(
                f"yt-dlp 下载失败：{last_error_line(result.stderr)}"
            )
        if not dest.exists() or dest.stat().st_size == 0:
            raise OMRError("yt-dlp 下载失败：未产出媒体文件。")
    finally:
        cleanup_download_parts(dest)


def extract_audio(media_path, audio_path):
    """用 ffmpeg 从媒体提取单声道音频。"""
    require_binary("ffmpeg", "提取音频")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(media_path), "-vn", "-ac", "1", str(audio_path)],
        capture_output=True, text=True,
    )
    if (
        result.returncode != 0
        or not audio_path.exists()
        or audio_path.stat().st_size == 0
    ):
        raise OMRError("ffmpeg 音频提取失败。")


def extract_frame(media_path, timestamp, dest):
    """用 ffmpeg 提取单个视频帧作为复核证据。"""
    require_binary("ffmpeg", "提取画面帧")
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(media_path),
         "-frames:v", "1", "-q:v", "3", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise OMRError(f"画面帧提取失败（{timestamp:.1f} 秒）。")


def transcribe_audio(
    audio_path, model, language=None, initial_prompt=None, download_root=None
):
    """调用 faster-whisper 转写，返回 [{start, end, text}] 段落。"""
    whisper_bin = os.environ.get("OMR_WHISPER_BIN")
    if whisper_bin:
        argv = [whisper_bin, str(audio_path), model]
    else:
        require_transcribe_deps()
        argv = [sys.executable, str(WHISPER_RUNNER), str(audio_path), model]
    if download_root:
        argv += ["--download-root", str(download_root)]
    if language:
        argv += ["--language", language]
    if initial_prompt:
        argv += ["--initial-prompt", initial_prompt]
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise OMRError(
            f"语音转写失败：{result.stderr.strip().splitlines()[-1] if result.stderr else '未知错误'}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise OMRError("语音转写失败：输出无法解析。")


def require_transcribe_deps():
    if "faster_whisper" not in sys.modules and importlib.util.find_spec(
        "faster_whisper"
    ) is None:
        raise OMRError("缺少 faster-whisper，无法执行语音转写。", exit_code=3)
