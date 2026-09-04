# -*- coding: utf-8 -*-
"""Ticket 03：抖音 URL 规范化、匿名 Cookie 格式与权限、摘要分离和失败关闭。

外部命令边界用假可执行文件替换；不访问真实网络。
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.request import HTTPCookieProcessor

MODULE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = MODULE_DIR / "scripts"
ENTRY = SCRIPTS / "read.py"

sys.path.insert(0, str(SCRIPTS))

from omr.adapters import douyin as douyin_adapter  # noqa: E402
from omr.model import OMRError  # noqa: E402
from test_video_pipeline import make_fakes, run_entry, calls  # noqa: E402


NO_SUBTITLE_FIXTURE = {
    "platform": "douyin",
    "original_url": "https://www.douyin.com/video/7000000000000000001",
    "canonical_url": "https://www.douyin.com/video/7000000000000000001",
    "content_type": "video",
    "title": "固定样本：抖音无字幕视频",
    "author": "示例作者",
    "published_at": "2026-08-10",
    "duration": 10,
    "subtitle_tracks": [],
    "media_items": [],
    "image_items": [],
    "summary": "AI 生成的章节要点摘要",
}

SUMMARY_FIXTURE = {
    "platform": "douyin",
    "original_url": "https://www.douyin.com/video/7000000000000000002",
    "canonical_url": "https://www.douyin.com/video/7000000000000000002",
    "content_type": "video",
    "title": "固定样本：带 AI 摘要视频",
    "author": "示例作者",
    "published_at": "2026-08-11",
    "duration": 10,
    "subtitle_tracks": [
        {
            "language": "zh-CN",
            "kind": "manual",
            "cues": [{"start": 0.0, "end": 10.0, "text": "人工字幕正文内容。"}],
        }
    ],
    "media_items": [],
    "image_items": [],
    "summary": "AI 生成的章节要点摘要",
}


def test_both_url_forms_resolve_to_same_video():
    detail = douyin_adapter.normalize_url("https://www.douyin.com/video/7000000000000000001")
    modal = douyin_adapter.normalize_url(
        "https://www.douyin.com/user/profile/MS4wLjABAAAA?modal_id=7000000000000000001"
    )
    assert detail == modal == ("7000000000000000001", "https://www.douyin.com/video/7000000000000000001")


def test_official_short_link_expands_with_probe_budget(monkeypatch):
    used = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://www.douyin.com/video/7000000000000000001"

    class Opener:
        def open(self, request, timeout):
            used["method"] = request.get_method()
            used["timeout"] = timeout
            return Response()

    class Budget:
        def remaining(self):
            return 12.5

    monkeypatch.setattr(douyin_adapter, "build_opener", lambda: Opener())

    result = douyin_adapter.normalize_url(
        "https://v.douyin.com/AbCdEf0/", budget=Budget()
    )

    assert result == (
        "7000000000000000001",
        "https://www.douyin.com/video/7000000000000000001",
    )
    assert used == {"method": "HEAD", "timeout": 12.5}


def test_router_data_selects_requested_video_id():
    def item(video_id, title):
        return {"aweme_id": video_id, "desc": title, "video": {}}

    html = (
        "<script>window._ROUTER_DATA = "
        + json.dumps(
            {
                "loaderData": {
                    "video/page": {
                        "videoInfoRes": {
                            "item_list": [
                                item("7000000000000000002", "错误缓存"),
                                item("7000000000000000001", "目标视频"),
                            ]
                        }
                    }
                }
            }
        )
        + "</script>"
    )

    selected = douyin_adapter._extract_item(html, "7000000000000000001")

    assert selected["desc"] == "目标视频"
    assert douyin_adapter._extract_item(html, "7000000000000000099") is None


def test_cookie_jar_format_and_permissions(tmp_path):
    jar = tmp_path / "cookies.txt"
    douyin_adapter.browser_session.write_cookie_jar(
        [{"name": "ttwid", "value": "abc123", "domain": ".douyin.com"}], jar
    )
    text = jar.read_text(encoding="utf-8")
    assert text.startswith("# Netscape HTTP Cookie File")
    assert ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc123" in text
    mode = stat.S_IMODE(jar.stat().st_mode)
    assert mode == 0o600


def test_cookie_file_is_created_private_before_secret_is_written(
    monkeypatch, tmp_path
):
    browser_session = douyin_adapter.browser_session
    original_open = browser_session.os.open
    created_modes = []

    def recording_open(path, flags, mode=0o777):
        created_modes.append(mode)
        return original_open(path, flags, mode)

    monkeypatch.setattr(browser_session.os, "open", recording_open)

    browser_session.write_cookie_jar(
        [{"name": "ttwid", "value": "secret", "domain": ".douyin.com"}],
        tmp_path / "cookies.txt",
    )

    assert created_modes == [0o600]


def test_cookie_opener_loads_browser_cookie_jar(tmp_path):
    jar = tmp_path / "cookies.txt"
    douyin_adapter.browser_session.write_cookie_jar(
        [{"name": "ttwid", "value": "abc123", "domain": ".douyin.com"}], jar
    )

    opener = douyin_adapter.cookie_opener(jar)

    processor = next(h for h in opener.handlers if isinstance(h, HTTPCookieProcessor))
    assert [cookie.name for cookie in processor.cookiejar] == ["ttwid"]


def test_fetch_converts_douyin_duration_from_milliseconds(monkeypatch, tmp_path):
    router_data = {
        "loaderData": {
            "note_(id)/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": "7000000000000000003",
                            "desc": "时长单位样本",
                            "video": {"duration": 12500},
                        }
                    ]
                }
            }
        }
    }
    html = (
        "<script>window._ROUTER_DATA = "
        + json.dumps(router_data)
        + "</script>"
    ).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return html

    class Opener:
        def open(self, request, timeout):
            return Response()

    monkeypatch.setattr(douyin_adapter, "make_opener", lambda: Opener())

    manifest = douyin_adapter.fetch(
        "https://www.douyin.com/video/7000000000000000003", tmp_path
    )

    assert manifest.duration == 12.5


def test_router_data_fail_closed_on_login_and_captcha():
    for marker in ("验证码", "登录后查看", "私密账号"):
        html = f"<html><body>{marker}</body></html>"
        try:
            douyin_adapter.parse_router_data(html)
        except OMRError as exc:
            assert marker in str(exc) or "无法访问" in str(exc)
        else:
            raise AssertionError(f"含 {marker} 的页面应失败关闭")


def test_summary_stays_out_of_subtitles(tmp_path):
    fixture = tmp_path / "summary.json"
    fixture.write_text(json.dumps(SUMMARY_FIXTURE, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000002",
        out,
        tmp_path,
        fixture=str(fixture),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：人工字幕" in text
    assert "人工字幕正文内容。" in text
    assert "平台摘要" in text
    assert "AI 生成的章节要点摘要" in text
    # 摘要不进入字幕正文
    assert text.index("人工字幕正文内容。") < text.index("AI 生成的章节要点摘要")


def test_douyin_no_subtitle_uses_shared_asr(tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    fixture = tmp_path / "nosub.json"
    fixture.write_text(
        json.dumps(
            dict(NO_SUBTITLE_FIXTURE, cookie_file=str(cookie)), ensure_ascii=False
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000001",
        out,
        tmp_path,
        fixture=str(fixture),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    assert "转写第一句。" in text
    invoked = calls(tmp_path)
    assert any(c.startswith("yt-dlp") for c in invoked)
    assert not cookie.exists()
    run_dir = Path(json.loads(result.stdout)["run_dir"])
    assert not (run_dir / "work").exists()
