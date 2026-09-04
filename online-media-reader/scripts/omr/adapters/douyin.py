# -*- coding: utf-8 -*-
"""抖音适配器：URL 规范化、公开元数据、字幕与 AI 章节摘要。

需要会话时经独立临时浏览器上下文取得匿名 Cookie；验证码、登录墙、
私密内容一律失败关闭，不重试、不绕过。
"""

import datetime
import re
from http.cookiejar import MozillaCookieJar
from urllib.parse import urlparse, parse_qs
from urllib.request import HTTPCookieProcessor, build_opener

from .. import browser_session
from ..model import ContentManifest, MediaSources, OMRError, SubtitleProbe, SubtitleTrack
from ..platform_http import (
    UA,
    fail_closed,
    make_opener,
    open_text,
    parse_embedded_json,
    request,
)
from ..router import official_host
from ..subtitles import (
    ProbeDeadlineExceeded,
    SubtitleProbeBudget,
    parse_webvtt,
    probe_for_track,
    run_probe_request,
    subtitle_priority,
)

_FAIL_MARKERS = ("验证码", "登录后查看", "私密账号", "内容不存在", "审核中")
_ROUTER_PATTERN = r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>"


def normalize_url(url, budget=None):
    """返回 (video_id, canonical_url)。支持 /video/<id> 与个人页 modal_id。"""
    parsed = urlparse(url)
    if parsed.hostname == "v.douyin.com":
        head = request(url)
        head.method = "HEAD"
        timeout = budget.remaining() if budget else 30
        with build_opener().open(head, timeout=timeout) as resp:
            url = resp.geturl()
        parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (
        official_host(host, "douyin.com")
        or official_host(host, "iesdouyin.com")
    ):
        raise OMRError(f"抖音链接展开结果不是官方域名：{url}", exit_code=4)
    m = re.search(r"/video/(\d+)", parsed.path)
    vid = m.group(1) if m else ""
    if not vid:
        modal = (parse_qs(parsed.query).get("modal_id") or [""])[0]
        if modal.isdigit():
            vid = modal
    if not vid:
        raise OMRError(f"无法从抖音链接解析视频 ID：{url}", exit_code=4)
    return vid, f"https://www.douyin.com/video/{vid}"


def parse_router_data(html):
    """从详情页 HTML 提取 _ROUTER_DATA；受限内容失败关闭。"""
    fail_closed(_FAIL_MARKERS, html, "抖音")
    return parse_embedded_json(html, _ROUTER_PATTERN, "抖音页面")


def cookie_opener(cookie_file):
    """加载浏览器生成的 Netscape Cookie 文件并创建 HTTP opener。"""
    jar = MozillaCookieJar(str(cookie_file))
    jar.load(ignore_discard=True, ignore_expires=True)
    opener = build_opener(HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def fetch(url, workdir, probe_only=False):
    budget = SubtitleProbeBudget()
    try:
        vid, canonical = normalize_url(url, budget=budget)
    except ProbeDeadlineExceeded as exc:
        return _probe_inaccessible(url, url, "unknown", str(exc), budget)
    cookie_file = None
    try:
        timeout = budget.remaining()
        item = _extract_item(_direct_html(canonical, timeout=timeout), vid)
    except ProbeDeadlineExceeded as exc:
        return _probe_inaccessible(url, canonical, vid, str(exc), budget)

    if item is None:
        # 详情页对无 Cookie 客户端返回 SPA 空壳；匿名会话 Cookie 会被
        # 302 到 m.douyin.com 分享页，该页 SSR 完整数据
        try:
            browser_timeout = budget.remaining()
            cookie_file = browser_session.anonymous_cookie_jar(
                "https://www.douyin.com/",
                workdir,
                timeout_ms=max(1, int(browser_timeout * 1000)),
            )
        except ProbeDeadlineExceeded as exc:
            return _probe_inaccessible(url, canonical, vid, str(exc), budget)
        except (OMRError, OSError, TimeoutError) as exc:
            return _probe_inaccessible(url, canonical, vid, str(exc), budget)
        opener = cookie_opener(cookie_file)
        try:
            timeout = budget.remaining()
            html = open_text(opener, request(canonical), timeout)
        except ProbeDeadlineExceeded as exc:
            return _probe_inaccessible(
                url, canonical, vid, str(exc), budget, cookie_file
            )
        except (OSError, TimeoutError) as exc:
            return _probe_inaccessible(
                url, canonical, vid, str(exc), budget, cookie_file
            )
        item = _extract_item(html, vid)

    if item is None:
        return _probe_inaccessible(
            url,
            canonical,
            vid,
            "抖音页面未返回请求视频的信息，可能非公开内容或页面结构已变化。",
            budget,
            cookie_file,
        )

    desc = (item.get("desc") or "").strip().splitlines()
    summary = item.get("ai_global_summary") or item.get("video_text") or ""
    duration_ms = (item.get("video") or {}).get("duration")
    duration = duration_ms / 1000 if duration_ms is not None else None
    tracks, subtitle_probe = _load_caption_tracks(
        item, duration, cookie_file, budget=budget
    )

    return ContentManifest(
        platform="douyin",
        original_url=url,
        canonical_url=canonical,
        content_type="video",
        title=desc[0] if desc else f"抖音视频 {vid}",
        author=(item.get("author") or {}).get("nickname", ""),
        published_at=datetime.date.fromtimestamp(item["create_time"]).isoformat()
        if item.get("create_time") else "",
        duration=duration,
        subtitle_tracks=tracks,
        subtitle_probe=subtitle_probe,
        summary=summary or None,
        cookie_file=str(cookie_file) if cookie_file else None,
        media_sources=_media_sources(item),
    )


def _direct_html(canonical, timeout=30):
    try:
        return open_text(make_opener(), request(canonical), timeout)
    except OSError:
        return ""


def _extract_item(html, expected_video_id=None):
    """从页面提取视频条目；空壳、无数据或解析失败返回 None，受限标记抛错。"""
    fail_closed(_FAIL_MARKERS, html, "抖音")
    m = re.search(_ROUTER_PATTERN, html, re.S)
    if not m:
        return None
    import json

    try:
        data = json.loads(re.sub(r":\s*undefined\b", ": null", m.group(1)))
    except ValueError:
        return None
    # www 站 key 为 note_(id)/page，m 站 SSR 为 video_(id)/page
    for value in (data.get("loaderData") or {}).values():
        items = ((value or {}).get("videoInfoRes") or {}).get("item_list") or []
        for item in items:
            if expected_video_id is None:
                return item
            item_id = item.get("aweme_id") or item.get("awemeId")
            if item_id is not None and str(item_id) == str(expected_video_id):
                return item
    return None


def _media_sources(item):
    """经 SSR 验证的合成流地址（音视频一体，playwm 重定向到 CDN）。"""
    play_addr = (item.get("video") or {}).get("play_addr") or {}
    urls = (play_addr.get("url_list") or [])
    if not urls:
        return MediaSources()
    return MediaSources(
        audio=urls[0],
        muxed=urls[0],
        referer="https://www.douyin.com/",
    )


def _load_caption_tracks(item, duration, cookie_file=None, budget=None):
    cla = (item.get("video") or {}).get("cla_info") or {}
    candidates = [
        cap
        for cap in cla.get("caption_infos") or []
        if cap.get("url")
        and cap.get("caption_format") in (None, "webvtt", "srt")
    ]
    if not candidates:
        return [], SubtitleProbe(
            status="absent",
            reason="平台没有返回独立字幕轨",
            elapsed_ms=budget.elapsed_ms if budget else 0,
        )

    def language(cap):
        return cap.get("lang") or cap.get("lang_str") or ""

    def kind(cap):
        return "manual" if cap.get("is_manual") else "auto"

    selected = min(
        candidates,
        key=lambda cap: subtitle_priority(language(cap), kind(cap)),
    )
    budget = budget or SubtitleProbeBudget()
    opener = cookie_opener(cookie_file) if cookie_file else make_opener()

    def download(timeout):
        return open_text(opener, request(selected["url"]), timeout)

    try:
        cues = parse_webvtt(run_probe_request(download, budget))
    except (ProbeDeadlineExceeded, OMRError, OSError) as exc:
        return [], SubtitleProbe(
            status="inaccessible", reason=str(exc), elapsed_ms=budget.elapsed_ms
        )
    except ValueError:
        return [], SubtitleProbe(
            status="invalid",
            reason="字幕正文格式无效",
            elapsed_ms=budget.elapsed_ms,
        )

    track = SubtitleTrack(language=language(selected), kind=kind(selected), cues=cues)
    return [track], probe_for_track(track, duration, budget.elapsed_ms)


def _probe_inaccessible(
    original_url, canonical, vid, reason, budget, cookie_file=None
):
    return ContentManifest(
        platform="douyin",
        original_url=original_url,
        canonical_url=canonical,
        content_type="video",
        title=f"抖音视频 {vid}",
        subtitle_probe=SubtitleProbe(
            status="inaccessible",
            reason=reason or "无法在探测预算内取得字幕元数据",
            elapsed_ms=budget.elapsed_ms if budget else 0,
        ),
        cookie_file=str(cookie_file) if cookie_file else None,
    )
