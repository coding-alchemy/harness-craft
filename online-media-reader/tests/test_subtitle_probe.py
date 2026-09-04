# -*- coding: utf-8 -*-
"""字幕探测总预算、候选选择、失败回退和只探测入口。"""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

MODULE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = MODULE_DIR / "scripts"
ENTRY = SCRIPTS / "read.py"

sys.path.insert(0, str(SCRIPTS))

from omr import pipeline, platform_http  # noqa: E402
from omr.adapters import bilibili, douyin  # noqa: E402
from omr.model import MediaSources, SubtitleCue, SubtitleTrack  # noqa: E402
from omr.subtitles import (  # noqa: E402
    ProbeDeadlineExceeded,
    SubtitleProbeBudget,
    assess_track,
    subtitle_priority,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload.encode("utf-8")


def bilibili_view():
    return {
        "code": 0,
        "data": {
            "title": "探测样本",
            "owner": {"name": "UP"},
            "pubdate": 0,
            "duration": 10,
            "pages": [{"cid": 123}],
        },
    }


def test_probe_budget_is_one_shared_30_second_deadline():
    ticks = iter([100.0, 105.0, 129.5, 130.0, 130.0])
    budget = SubtitleProbeBudget(30, clock=lambda: next(ticks))

    assert budget.remaining() == pytest.approx(25.0)
    assert budget.remaining() == pytest.approx(0.5)
    with pytest.raises(ProbeDeadlineExceeded):
        budget.remaining()
    assert budget.elapsed_ms == 30000


def test_subtitle_coverage_merges_overlaps_and_checks_tail_gap():
    track = SubtitleTrack(
        language="zh-CN",
        kind="manual",
        cues=[
            SubtitleCue(start=0, end=50, text="前半段"),
            SubtitleCue(start=0, end=50, text="重复前半段"),
        ],
    )

    reliable, issues = assess_track(track, duration=100)

    assert reliable is False
    assert "覆盖率 50% 低于 80%" in issues
    assert "存在 50 秒尾部覆盖缺口" in issues


def test_subtitle_range_beyond_video_duration_is_invalid():
    track = SubtitleTrack(
        language="zh-CN",
        kind="manual",
        cues=[SubtitleCue(start=0, end=200, text="错误的超长字幕")],
    )

    reliable, issues = assess_track(track, duration=100)

    assert reliable is False
    assert "字幕时间范围超出视频时长" in issues


def test_unknown_duration_still_rejects_obvious_internal_gap():
    track = SubtitleTrack(
        language="zh-CN",
        kind="manual",
        cues=[
            SubtitleCue(start=0, end=1, text="第一句"),
            SubtitleCue(start=1000, end=1001, text="第二句"),
        ],
    )

    reliable, issues = assess_track(track, duration=None)

    assert reliable is False
    assert "存在 999 秒覆盖缺口" in issues


def test_blank_cues_do_not_count_toward_subtitle_coverage():
    track = SubtitleTrack(
        language="zh-CN",
        kind="manual",
        cues=[
            SubtitleCue(start=0, end=1, text="唯一正文"),
            SubtitleCue(start=1, end=100, text="   "),
        ],
    )

    reliable, issues = assess_track(track, duration=100)

    assert reliable is False
    assert "覆盖率 1% 低于 80%" in issues
    assert "存在 99 秒尾部覆盖缺口" in issues


@pytest.mark.parametrize(
    ("duration", "cue", "minimum"),
    [
        (600, SubtitleCue(start=0, end=600, text="嗯"), 20),
        (None, SubtitleCue(start=0, end=1, text="广告"), 4),
    ],
)
def test_sparse_subtitle_text_is_not_reliable(duration, cue, minimum):
    track = SubtitleTrack(language="zh-CN", kind="manual", cues=[cue])

    reliable, issues = assess_track(track, duration=duration)

    assert reliable is False
    assert f"字幕文本少于 {minimum} 个字符" in issues


def test_ai_zh_is_ranked_as_chinese_automatic_subtitle():
    assert subtitle_priority("ai-zh", "auto") < subtitle_priority(
        "en-US", "manual"
    )


def test_http_412_fallback_uses_only_remaining_request_budget(monkeypatch):
    class RejectedOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 412, "blocked", {}, None)

    ticks = iter([100.0, 110.0])
    used = {}
    monkeypatch.setattr(platform_http, "build_opener", lambda: RejectedOpener())
    monkeypatch.setattr(platform_http, "monotonic", lambda: next(ticks))

    def fake_curl(url, headers, timeout):
        used["timeout"] = timeout
        return "ok"

    monkeypatch.setattr(platform_http, "_curl_text", fake_curl)

    assert platform_http.fetch_text("https://example.com", timeout=30) == "ok"
    assert used["timeout"] == pytest.approx(20)


def test_http_response_body_read_obeys_absolute_deadline(monkeypatch):
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read1(self, _size):
            return b"x"

    class SlowOpener:
        def open(self, _request, timeout):
            assert timeout == 30
            return SlowResponse()

    ticks = iter([0.0, 0.0, 10.0, 31.0])
    monkeypatch.setattr(platform_http, "build_opener", lambda: SlowOpener())
    monkeypatch.setattr(platform_http, "monotonic", lambda: next(ticks))

    with pytest.raises(TimeoutError, match="超过 30 秒"):
        platform_http.fetch_text("https://example.com", timeout=30)


def test_bilibili_probe_downloads_only_best_subtitle(monkeypatch, tmp_path):
    monkeypatch.setattr(bilibili, "_get_json", lambda url, timeout=30: bilibili_view())
    requested = []

    def fake_fetch_text(url, ua=None, referer=None, timeout=30):
        requested.append((url, timeout))
        if url.startswith(bilibili.PLAYER_API):
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "subtitle": {
                            "subtitles": [
                                {
                                    "lan": "zh-CN",
                                    "ai_type": 1,
                                    "subtitle_url": "https://subs/zh-auto",
                                },
                                {
                                    "lan": "en-US",
                                    "ai_type": 0,
                                    "subtitle_url": "https://subs/en-manual",
                                },
                                {
                                    "lan": "zh-CN",
                                    "ai_type": 0,
                                    "subtitle_url": "https://subs/zh-manual",
                                },
                            ]
                        }
                    },
                }
            )
        if url == "https://subs/zh-manual":
            return json.dumps(
                {"body": [{"from": 0, "to": 10, "content": "完整人工字幕"}]}
            )
        raise AssertionError(f"不应请求字幕：{url}")

    monkeypatch.setattr(bilibili, "fetch_text", fake_fetch_text)

    manifest = bilibili.fetch(
        "https://www.bilibili.com/video/BV1sample000", tmp_path, probe_only=True
    )

    assert manifest.subtitle_probe.status == "usable"
    assert [url for url, _ in requested] == [
        f"{bilibili.PLAYER_API}?bvid=BV1sample000&cid=123",
        "https://subs/zh-manual",
    ]
    assert all(0 < timeout <= 30 for _, timeout in requested)


def test_bilibili_uses_selected_page_duration_for_subtitle_quality(
    monkeypatch, tmp_path
):
    view = bilibili_view()
    view["data"]["duration"] = 100
    view["data"]["pages"] = [
        {"cid": 111, "duration": 90},
        {"cid": 222, "duration": 10},
    ]
    monkeypatch.setattr(bilibili, "_get_json", lambda url, timeout=30: view)

    def fake_fetch_text(url, **_kwargs):
        if url.startswith(bilibili.PLAYER_API):
            assert "cid=222" in url
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "subtitle": {
                            "subtitles": [
                                {
                                    "lan": "zh-CN",
                                    "ai_type": 0,
                                    "subtitle_url": "https://subs/page-2",
                                }
                            ]
                        }
                    },
                }
            )
        return json.dumps(
            {"body": [{"from": 0, "to": 10, "content": "第二分 P 字幕"}]}
        )

    monkeypatch.setattr(bilibili, "fetch_text", fake_fetch_text)

    manifest = bilibili.fetch(
        "https://www.bilibili.com/video/BV1sample000?p=2",
        tmp_path,
        probe_only=True,
    )

    assert manifest.duration == 10
    assert manifest.subtitle_probe.status == "usable"


def test_douyin_probe_downloads_only_best_subtitle(monkeypatch, tmp_path):
    item = {
        "aweme_id": "7000000000000000003",
        "desc": "探测样本",
        "video": {
            "duration": 10000,
            "cla_info": {
                "caption_infos": [
                    {
                        "lang": "zh-CN",
                        "caption_format": "webvtt",
                        "url": "https://subs/zh-auto",
                    },
                    {
                        "lang": "zh-CN",
                        "caption_format": "webvtt",
                        "is_manual": True,
                        "url": "https://subs/zh-manual",
                    },
                ]
            },
        },
    }
    router_data = {
        "loaderData": {"note_(id)/page": {"videoInfoRes": {"item_list": [item]}}}
    }
    html = f'<script>window._ROUTER_DATA = {json.dumps(router_data)}</script>'
    monkeypatch.setattr(douyin, "_direct_html", lambda url, timeout=30: html)
    requested = []

    class Opener:
        def open(self, req, timeout):
            requested.append((req.full_url, timeout))
            if req.full_url != "https://subs/zh-manual":
                raise AssertionError(f"不应请求字幕：{req.full_url}")
            return Response("WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n完整人工字幕")

    monkeypatch.setattr(douyin, "make_opener", lambda: Opener())

    manifest = douyin.fetch(
        "https://www.douyin.com/video/7000000000000000003", tmp_path, probe_only=True
    )

    assert manifest.subtitle_probe.status == "usable"
    assert [url for url, _ in requested] == ["https://subs/zh-manual"]
    assert 0 < requested[0][1] <= 30


def test_douyin_probe_uses_browser_path_and_shared_remaining_budget(
    monkeypatch, tmp_path
):
    item = {
        "aweme_id": "7000000000000000003",
        "desc": "浏览器探测样本",
        "video": {
            "duration": 10000,
            "cla_info": {
                "caption_infos": [
                    {
                        "lang": "zh-CN",
                        "caption_format": "webvtt",
                        "is_manual": True,
                        "url": "https://subs/manual",
                    }
                ]
            },
        },
    }
    router_data = {
        "loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [item]}}}
    }
    html = f'<script>window._ROUTER_DATA = {json.dumps(router_data)}</script>'
    used = []

    class FakeBudget:
        seconds = 30
        elapsed_ms = 15000

        def __init__(self):
            self.values = iter([30, 25, 20, 15])

        def remaining(self):
            value = next(self.values)
            used.append(("budget", value))
            return value

    monkeypatch.setattr(douyin, "SubtitleProbeBudget", FakeBudget)
    monkeypatch.setattr(
        douyin,
        "_direct_html",
        lambda _url, timeout=30: used.append(("direct", timeout)) or "",
    )

    def fake_cookie_jar(_url, workdir, timeout_ms=30000):
        used.append(("browser", timeout_ms))
        cookie = workdir / "cookies.txt"
        cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        return cookie

    monkeypatch.setattr(
        douyin.browser_session, "anonymous_cookie_jar", fake_cookie_jar
    )

    class Opener:
        def open(self, req, timeout):
            used.append(("open", req.full_url, timeout))
            if req.full_url == "https://subs/manual":
                return Response(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n完整人工字幕"
                )
            return Response(html)

    monkeypatch.setattr(douyin, "cookie_opener", lambda _cookie: Opener())

    manifest = douyin.fetch(
        "https://www.douyin.com/video/7000000000000000003",
        tmp_path,
        probe_only=True,
    )

    assert manifest.subtitle_probe.status == "usable"
    assert ("direct", 30) in used
    assert ("browser", 25000) in used
    assert ("open", manifest.canonical_url, 20) in used
    assert ("open", "https://subs/manual", 15) in used

    normal_workdir = tmp_path / "normal"
    normal_workdir.mkdir()
    normal = douyin.fetch(
        "https://www.douyin.com/video/7000000000000000003",
        normal_workdir,
        probe_only=False,
    )
    assert normal.subtitle_probe.status == manifest.subtitle_probe.status == "usable"


def test_douyin_probe_browser_failure_returns_asr_decision(monkeypatch, tmp_path):
    from omr.model import OMRError

    monkeypatch.setattr(douyin, "_direct_html", lambda _url, timeout=30: "")
    monkeypatch.setattr(
        douyin.browser_session,
        "anonymous_cookie_jar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OMRError("匿名浏览器访问失败：timeout", exit_code=4)
        ),
    )

    manifest = douyin.fetch(
        "https://www.douyin.com/video/7000000000000000003",
        tmp_path,
        probe_only=True,
    )

    assert manifest.subtitle_probe.status == "inaccessible"
    assert "timeout" in manifest.subtitle_probe.reason

    normal = douyin.fetch(
        "https://www.douyin.com/video/7000000000000000003",
        tmp_path,
        probe_only=False,
    )
    assert normal.subtitle_probe.status == "inaccessible"
    assert "timeout" in normal.subtitle_probe.reason


def test_anonymous_browser_launch_and_navigation_share_timeout(
    monkeypatch, tmp_path
):
    from omr import browser_session

    used = {}

    class Page:
        def goto(self, _url, wait_until, timeout):
            used["goto"] = (wait_until, timeout)

    class Context:
        def new_page(self):
            return Page()

        def cookies(self):
            return []

    class Browser:
        def new_context(self):
            return Context()

        def close(self):
            pass

    class Chromium:
        def launch(self, headless, timeout=None):
            used["launch"] = (headless, timeout)
            return Browser()

    class Playwright:
        chromium = Chromium()

        def stop(self):
            pass

    ticks = iter([100.0, 105.0, 110.0])
    monkeypatch.setattr(browser_session, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(browser_session, "_chromium", lambda: Playwright())

    cookies = browser_session._collect_cookies(
        "https://www.douyin.com/", timeout_ms=30000
    )

    assert cookies == []
    assert used["launch"] == (True, 25000)
    assert used["goto"] == ("domcontentloaded", 20000)


def test_anonymous_browser_driver_is_bounded_by_parent_timeout(
    monkeypatch, tmp_path
):
    from omr import browser_session
    from omr.model import OMRError

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired("browser-runner", 30)

    monkeypatch.setattr(browser_session.subprocess, "run", timeout)

    with pytest.raises(OMRError, match="共享字幕探测预算"):
        browser_session.anonymous_cookie_jar(
            "https://www.douyin.com/", tmp_path, timeout_ms=30000
        )


def test_anonymous_browser_runner_returns_private_cookie_file(
    monkeypatch, tmp_path
):
    from omr import browser_session

    payload = {
        "cookies": [
            {
                "name": "ttwid",
                "value": "value",
                "domain": ".douyin.com",
            }
        ]
    }

    def success(argv, **kwargs):
        assert argv[1] == str(browser_session.BROWSER_RUNNER)
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(browser_session.subprocess, "run", success)

    cookie = browser_session.anonymous_cookie_jar(
        "https://www.douyin.com/", tmp_path, timeout_ms=30000
    )

    assert "ttwid\tvalue" in cookie.read_text(encoding="utf-8")
    assert cookie.stat().st_mode & 0o777 == 0o600


def test_bilibili_null_caption_text_returns_invalid_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(bilibili, "_get_json", lambda url, timeout=30: bilibili_view())

    def fake_fetch_text(url, ua=None, referer=None, timeout=30):
        if url.startswith(bilibili.PLAYER_API):
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "subtitle": {
                            "subtitles": [
                                {
                                    "lan": "zh-CN",
                                    "ai_type": 0,
                                    "subtitle_url": "https://subs/damaged",
                                }
                            ]
                        }
                    },
                }
            )
        return json.dumps(
            {"body": [{"from": 0, "to": 10, "content": None}]}
        )

    monkeypatch.setattr(bilibili, "fetch_text", fake_fetch_text)

    manifest = bilibili.fetch(
        "https://www.bilibili.com/video/BV1sample000",
        tmp_path,
        probe_only=True,
    )

    assert manifest.subtitle_probe.status == "invalid"
    assert "字幕文本为空" in manifest.subtitle_probe.reason

    monkeypatch.setattr(
        pipeline.media,
        "download_media",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"media"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "extract_audio",
        lambda _source, dest: dest.write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda *_args, **_kwargs: [
            {"start": 0, "end": 1, "text": "ASR 正文"}
        ],
    )
    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")

    from omr.render import render_markdown

    markdown = render_markdown(manifest)
    assert "ASR 正文" in markdown
    assert "] None" not in markdown


def test_bilibili_non_object_caption_cue_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bilibili, "_get_json", lambda url, timeout=30: bilibili_view()
    )

    def fake_fetch_text(url, ua=None, referer=None, timeout=30):
        if url.startswith(bilibili.PLAYER_API):
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "subtitle": {
                            "subtitles": [
                                {
                                    "lan": "zh-CN",
                                    "ai_type": 0,
                                    "subtitle_url": "https://subs/mixed",
                                }
                            ]
                        }
                    },
                }
            )
        return json.dumps(
            {
                "body": [
                    None,
                    {"from": 0, "to": 10, "content": "完整正文"},
                ]
            }
        )

    monkeypatch.setattr(bilibili, "fetch_text", fake_fetch_text)

    manifest = bilibili.fetch(
        "https://www.bilibili.com/video/BV1sample000",
        tmp_path,
        probe_only=True,
    )

    assert manifest.subtitle_probe.status == "usable"
    assert [cue.text for cue in manifest.subtitle_tracks[0].cues] == ["完整正文"]


def test_webvtt_cue_identifier_is_not_included_in_text():
    from omr.subtitles import parse_webvtt

    cues = parse_webvtt(
        "WEBVTT\n\ncue-id\n00:00:00.000 --> 00:00:01.000\n正文\n"
    )

    assert [cue.text for cue in cues] == ["正文"]


def test_render_state_is_bounded_by_parent_timeout(monkeypatch):
    from omr import browser_session
    from omr.model import OMRError

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired("browser-runner", 30)

    monkeypatch.setattr(browser_session.subprocess, "run", timeout)

    with pytest.raises(OMRError, match="浏览器渲染超过 30 秒预算"):
        browser_session.render_state(
            "https://www.xiaohongshu.com/", "() => null", timeout_ms=30000
        )


def test_bilibili_short_link_expansion_shares_probe_budget(monkeypatch, tmp_path):
    budget = SubtitleProbeBudget(30, clock=lambda: 100.0)
    remaining = iter([20.0, 10.0])
    monkeypatch.setattr(budget, "remaining", lambda: next(remaining))
    monkeypatch.setattr(bilibili, "SubtitleProbeBudget", lambda: budget)
    used = {}

    def resolve(_url, timeout):
        used["short"] = timeout
        return "https://www.bilibili.com/video/BV1sample000"

    def get_json(_url, timeout=30):
        used["view"] = timeout
        return bilibili_view()

    monkeypatch.setattr(bilibili, "resolve_short_link", resolve)
    monkeypatch.setattr(bilibili, "_get_json", get_json)
    monkeypatch.setattr(
        bilibili,
        "_probe_subtitle_tracks",
        lambda *_args, **_kwargs: ([], bilibili.SubtitleProbe(status="absent")),
    )

    bilibili.fetch("https://b23.tv/abcDEF0", tmp_path, probe_only=True)

    assert used == {"short": 20.0, "view": 10.0}


def test_bilibili_media_sources_keep_best_and_bounded_review_video(monkeypatch):
    monkeypatch.setattr(
        bilibili,
        "_get_json",
        lambda _url: {
            "data": {
                "dash": {
                    "audio": [
                        {"bandwidth": 128_000, "baseUrl": "https://cdn/audio.m4s"}
                    ],
                    "video": [
                        {
                            "height": 720,
                            "bandwidth": 3_000_000,
                            "baseUrl": "https://cdn/720p.m4s",
                        },
                        {
                            "height": 480,
                            "bandwidth": 2_000_000,
                            "baseUrl": "https://cdn/480p.m4s",
                        },
                        {
                            "height": 360,
                            "bandwidth": 800_000,
                            "baseUrl": "https://cdn/360p.m4s",
                        },
                    ],
                }
            }
        },
    )

    sources = bilibili._resolve_media_sources("BV1sample000", 123)

    assert sources.video == "https://cdn/720p.m4s"
    assert sources.review_video == "https://cdn/480p.m4s"


def test_bilibili_subtitle_failure_falls_back_to_asr(monkeypatch, tmp_path):
    monkeypatch.setattr(bilibili, "_get_json", lambda url, timeout=30: bilibili_view())
    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(args[0])
        raise TimeoutError("字幕接口超时")

    monkeypatch.setattr(bilibili, "fetch_text", unavailable)
    monkeypatch.setattr(bilibili, "_resolve_media_sources", lambda *args: MediaSources())
    manifest = bilibili.fetch(
        "https://www.bilibili.com/video/BV1sample000", tmp_path
    )
    assert len(attempts) == 2
    assert manifest.subtitle_probe.status == "inaccessible"

    monkeypatch.setattr(
        pipeline.media,
        "download_media",
        lambda url, dest, mode, cookies=None: dest.write_bytes(b"media"),
    )
    monkeypatch.setattr(
        pipeline.media, "extract_audio", lambda source, dest: dest.write_bytes(b"audio")
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda audio, model, **kwargs: [{"start": 0, "end": 5, "text": "ASR 正文"}],
    )

    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")

    assert manifest.processing_path == "语音转写（ASR）"
    assert manifest.subtitle_tracks[0].cues[0].text == "ASR 正文"


def test_probe_only_outputs_json_without_media_or_asr(tmp_path):
    fixture = tmp_path / "subtitle.json"
    fixture.write_text(
        json.dumps(
            {
                "platform": "bilibili",
                "original_url": "https://www.bilibili.com/video/BV1sample00",
                "canonical_url": "https://www.bilibili.com/video/BV1sample00",
                "content_type": "video",
                "title": "探测样本",
                "duration": 10,
                "subtitle_tracks": [
                    {
                        "language": "zh-CN",
                        "kind": "manual",
                        "cues": [{"start": 0, "end": 10, "text": "完整字幕"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calllog = tmp_path / "calls.log"
    env = dict(os.environ)
    env["OMR_FIXTURE"] = str(fixture)
    env["OMR_CALLLOG"] = str(calllog)

    result = subprocess.run(
        [
            sys.executable,
            str(ENTRY),
            "https://www.bilibili.com/video/BV1sample00",
            "--probe-only",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "decision": "use_subtitle",
        "status": "usable",
        "reason": "字幕已下载并通过质量检查",
        "elapsed_ms": 0,
    }
    assert not calllog.exists()
    assert list(tmp_path.glob("*.md")) == []

    data = json.loads(fixture.read_text(encoding="utf-8"))
    data["subtitle_tracks"] = []
    fixture.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ENTRY),
            "https://www.bilibili.com/video/BV1sample00",
            "--probe-only",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "use_asr"
    assert json.loads(result.stdout)["status"] == "absent"
    assert not (tmp_path / ".media").exists()
