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


def test_cookie_jar_format_and_permissions(work_root):
    jar = work_root / "cookies.txt"
    douyin_adapter.browser_session.write_cookie_jar(
        [{"name": "ttwid", "value": "abc123", "domain": ".douyin.com"}], jar
    )
    text = jar.read_text(encoding="utf-8")
    assert text.startswith("# Netscape HTTP Cookie File")
    assert ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc123" in text
    mode = stat.S_IMODE(jar.stat().st_mode)
    assert mode == 0o600


def test_cookie_file_is_created_private_before_secret_is_written(
    monkeypatch, work_root
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
        work_root / "cookies.txt",
    )

    assert created_modes == [0o600]


def test_cookie_opener_loads_browser_cookie_jar(work_root):
    jar = work_root / "cookies.txt"
    douyin_adapter.browser_session.write_cookie_jar(
        [{"name": "ttwid", "value": "abc123", "domain": ".douyin.com"}], jar
    )

    opener = douyin_adapter.cookie_opener(jar)

    processor = next(h for h in opener.handlers if isinstance(h, HTTPCookieProcessor))
    assert [cookie.name for cookie in processor.cookiejar] == ["ttwid"]


def test_fetch_converts_douyin_duration_from_milliseconds(monkeypatch, work_root):
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
        "https://www.douyin.com/video/7000000000000000003", work_root
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


def test_summary_stays_out_of_subtitles(work_root):
    fixture = work_root / "summary.json"
    fixture.write_text(json.dumps(SUMMARY_FIXTURE, ensure_ascii=False), encoding="utf-8")
    out = work_root / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000002",
        out,
        work_root,
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


def test_douyin_no_subtitle_uses_shared_asr(work_root):
    cookie = work_root / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    fixture = work_root / "nosub.json"
    fixture.write_text(
        json.dumps(
            dict(NO_SUBTITLE_FIXTURE, cookie_file=str(cookie)), ensure_ascii=False
        ),
        encoding="utf-8",
    )
    out = work_root / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000001",
        out,
        work_root,
        fixture=str(fixture),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    assert "转写第一句。" in text
    invoked = calls(work_root)
    assert any(c.startswith("yt-dlp") for c in invoked)
    assert not cookie.exists()
    run_dir = Path(json.loads(result.stdout)["run_dir"])
    assert not (run_dir / "work").exists()


# ---------------------------------------------------------- gallery-and-durable-evidence ticket 03

GALLERY_NOTE_ID = "7422510759139183906"


def _gallery_item(note_id=GALLERY_NOTE_ID, image_count=2, with_images=True):
    item = {
        "aweme_id": note_id,
        "aweme_type": 2,
        "desc": "固定样本：抖音图文标题\n第二行说明",
        "author": {"nickname": "示例图文作者"},
        "create_time": 1750000000,
        "music": {},
        "video": {},
    }
    if with_images:
        item["images"] = [
            {
                "url_list": [f"https://p3-sign.douyinpic.com/img-{i}-a"],
                "download_url_list": [f"https://p3-sign.douyinpic.com/img-{i}-dl"],
            }
            for i in range(1, image_count + 1)
        ]
    return item


def _gallery_html(item, note_id=GALLERY_NOTE_ID):
    data = {
        "loaderData": {
            f"note_({note_id})/page": {"videoInfoRes": {"item_list": [item]}}
        }
    }
    return "<script>window._ROUTER_DATA = " + json.dumps(data) + "</script>"


def test_note_url_normalizes_keeping_note_form():
    vid, canonical = douyin_adapter.normalize_url(
        f"https://www.douyin.com/note/{GALLERY_NOTE_ID}"
    )
    assert vid == GALLERY_NOTE_ID
    assert canonical == f"https://www.douyin.com/note/{GALLERY_NOTE_ID}"


def test_short_link_expanding_to_note_keeps_note_form(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return f"https://www.douyin.com/note/{GALLERY_NOTE_ID}"

    class Opener:
        def open(self, request, timeout):
            return Response()

    monkeypatch.setattr(douyin_adapter, "build_opener", lambda: Opener())
    vid, canonical = douyin_adapter.normalize_url("https://v.douyin.com/AbCdEf0/")
    assert vid == GALLERY_NOTE_ID
    assert canonical == f"https://www.douyin.com/note/{GALLERY_NOTE_ID}"


def test_workspace_content_id_parses_note_url():
    sys.path.insert(0, str(SCRIPTS))
    from omr.workspace import content_id_from_url

    assert (
        content_id_from_url("douyin", f"https://www.douyin.com/note/{GALLERY_NOTE_ID}")
        == GALLERY_NOTE_ID
    )


def test_router_accepts_note_detail_and_existing_video_entries():
    from omr.router import detect_platform

    assert detect_platform(f"https://www.douyin.com/note/{GALLERY_NOTE_ID}") == "douyin"
    assert detect_platform("https://www.douyin.com/video/7000000000000000001") == "douyin"
    assert (
        detect_platform("https://www.douyin.com/user/self?modal_id=7000000000000000001")
        == "douyin"
    )


def test_gallery_item_routes_to_image_gallery(monkeypatch, work_root):
    monkeypatch.setattr(
        douyin_adapter, "_direct_html",
        lambda canonical, timeout=30: _gallery_html(_gallery_item()),
    )
    manifest = douyin_adapter.fetch(
        f"https://www.douyin.com/note/{GALLERY_NOTE_ID}", work_root
    )

    assert manifest.content_type == "image_gallery"
    assert [img.index for img in manifest.image_items] == [1, 2]
    assert manifest.image_items[0].url == "https://p3-sign.douyinpic.com/img-1-a"
    assert all(img.ocr_text is None for img in manifest.image_items)
    assert manifest.subtitle_tracks == []
    assert manifest.media_sources.audio is None and manifest.media_sources.muxed is None
    assert manifest.duration is None


def test_gallery_via_modal_id_entry_routes_to_image_gallery(monkeypatch, work_root):
    monkeypatch.setattr(
        douyin_adapter, "_direct_html",
        lambda canonical, timeout=30: _gallery_html(_gallery_item()),
    )
    manifest = douyin_adapter.fetch(
        "https://www.douyin.com/user/profile/abc?modal_id=" + GALLERY_NOTE_ID,
        work_root,
    )
    assert manifest.content_type == "image_gallery"
    assert manifest.image_items[0].url == "https://p3-sign.douyinpic.com/img-1-a"


def test_gallery_item_without_images_fails_closed(monkeypatch):
    monkeypatch.setattr(
        douyin_adapter, "_direct_html",
        lambda canonical, timeout=30: _gallery_html(_gallery_item(with_images=False)),
    )
    try:
        douyin_adapter.fetch(
            f"https://www.douyin.com/note/{GALLERY_NOTE_ID}", Path(".")
        )
    except OMRError as exc:
        assert "图文" in str(exc)
    else:
        raise AssertionError("已知图文缺图必须明确失败")


def test_gallery_download_uses_image_url_not_video(monkeypatch, work_root):
    """分流后不进入视频媒体提取：media_sources 保持为空（无 playwm/合成流）。"""
    monkeypatch.setattr(
        douyin_adapter, "_direct_html",
        lambda canonical, timeout=30: _gallery_html(_gallery_item()),
    )
    manifest = douyin_adapter.fetch(
        f"https://www.douyin.com/note/{GALLERY_NOTE_ID}", work_root
    )
    assert manifest.media_sources == douyin_adapter.MediaSources()
