# -*- coding: utf-8 -*-
"""B站适配器：长短链接规范化、当前分 P 元数据与字幕轨读取。

只处理 URL 指向的当前视频或分 P；不访问账号内容。页面结构变化导致的
提取失败会以明确错误报告，与“确认无字幕”区分。
"""

import datetime
import json
import re
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, build_opener

from ..model import (
    ContentManifest,
    MediaSources,
    OMRError,
    SubtitleCue,
    SubtitleProbe,
    SubtitleTrack,
)
from ..platform_http import UA_DESKTOP, fetch_text
from ..router import official_host
from ..subtitles import (
    ProbeDeadlineExceeded,
    SubtitleProbeBudget,
    probe_for_track,
    run_probe_request,
    subtitle_priority,
)

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAYER_API = "https://api.bilibili.com/x/player/wbi/v2"
PLAYURL_API = "https://api.bilibili.com/x/player/playurl"


def _get_json(url, timeout=30):
    try:
        payload = fetch_text(
            url,
            ua=UA_DESKTOP,
            referer="https://www.bilibili.com/",
            timeout=timeout,
        )
        return json.loads(payload)
    except ValueError:
        raise OMRError("B站接口返回数据解析失败，页面结构可能已变化。", exit_code=4)
    except OSError:
        raise OMRError("B站接口访问失败。访问失败不等同于确认无字幕。", exit_code=4)


def resolve_short_link(url, timeout=30):
    """展开 b23.tv 短链接，返回最终 URL。"""
    head = Request(url, headers={"User-Agent": UA_DESKTOP}, method="HEAD")
    with build_opener().open(head, timeout=timeout) as resp:
        return resp.geturl()


def normalize_url(url, budget=None):
    if urlparse(url).hostname == "b23.tv":
        timeout = budget.remaining() if budget else 30
        url = resolve_short_link(url, timeout)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not official_host(host, "bilibili.com"):
        raise OMRError(f"B站链接展开结果不是 bilibili.com：{url}", exit_code=4)
    m = re.search(r"/(BV[0-9A-Za-z]{10,})", parsed.path)
    if not m:
        raise OMRError(f"无法从链接中识别视频 BV 号：{url}", exit_code=4)
    bvid = m.group(1)
    page = int((parse_qs(parsed.query).get("p") or ["1"])[0])
    canonical = f"https://www.bilibili.com/video/{bvid}"
    if page > 1:
        canonical += f"?p={page}"
    return bvid, page, canonical


def fetch(url, workdir, probe_only=False):
    budget = SubtitleProbeBudget()
    try:
        bvid, page, canonical = normalize_url(url, budget=budget)
    except ProbeDeadlineExceeded as exc:
        return _inaccessible_manifest(url, url, "unknown", str(exc), budget)

    try:
        view = _get_json(f"{VIEW_API}?bvid={bvid}", timeout=budget.remaining())
    except (ProbeDeadlineExceeded, OMRError) as exc:
        return _inaccessible_manifest(url, canonical, bvid, str(exc), budget)
    if view.get("code") != 0:
        raise OMRError(f"B站视频信息获取失败：{view.get('message', '未知错误')}", exit_code=4)
    data = view["data"]
    pages = data.get("pages", [])
    if not (1 <= page <= max(len(pages), 1)):
        raise OMRError(f"分 P 超出范围：p={page}", exit_code=4)
    page_data = pages[page - 1] if pages else data
    cid = page_data["cid"]
    duration = page_data.get("duration") or data.get("duration")

    tracks, subtitle_probe = _probe_subtitle_tracks(
        bvid, cid, duration, budget=budget
    )
    media_sources = MediaSources() if probe_only else _resolve_media_sources(bvid, cid)

    return ContentManifest(
        platform="bilibili",
        original_url=url,
        canonical_url=canonical,
        content_type="video",
        title=data.get("title", ""),
        author=(data.get("owner") or {}).get("name", ""),
        published_at=datetime.date.fromtimestamp(data["pubdate"]).isoformat()
        if data.get("pubdate") else "",
        duration=duration,
        subtitle_tracks=tracks,
        subtitle_probe=subtitle_probe,
        media_sources=media_sources,
    )


def _resolve_media_sources(bvid, cid):
    """经 playurl 接口验证的直连媒体地址（B站对 yt-dlp 网页访问返回 412）。"""
    try:
        payload = _get_json(
            f"{PLAYURL_API}?bvid={bvid}&cid={cid}&fnval=16&qn=64"
        )
    except OMRError:
        return MediaSources()
    dash = (payload.get("data") or {}).get("dash") or {}
    audios = dash.get("audio") or []
    videos = dash.get("video") or []
    if not audios:
        return MediaSources()

    def item_url(item):
        return item.get("baseUrl") or (item.get("backupUrl") or [""])[0]

    def best_url(items):
        return item_url(max(items, key=lambda i: i.get("bandwidth") or 0))

    def review_url(items):
        bounded = [item for item in items if 0 < (item.get("height") or 0) <= 480]
        if bounded:
            return best_url(bounded)
        return item_url(min(items, key=lambda i: i.get("bandwidth") or 0))

    return MediaSources(
        audio=best_url(audios),
        video=best_url(videos) if videos else None,
        review_video=review_url(videos) if videos else None,
        referer="https://www.bilibili.com/",
    )


def _subtitle_kind(sub):
    return (
        "auto"
        if sub.get("ai_type") == 1 or sub.get("lan", "").startswith("ai-")
        else "manual"
    )


def _probe_json(url, budget):
    return run_probe_request(
        lambda timeout: json.loads(
            fetch_text(
                url,
                ua=UA_DESKTOP,
                referer="https://www.bilibili.com/",
                timeout=timeout,
            )
        ),
        budget,
    )


def _probe_subtitle_tracks(bvid, cid, duration, budget=None):
    budget = budget or SubtitleProbeBudget()
    try:
        player = _probe_json(f"{PLAYER_API}?bvid={bvid}&cid={cid}", budget)
    except (ProbeDeadlineExceeded, OMRError, OSError) as exc:
        return [], SubtitleProbe(
            status="inaccessible", reason=str(exc), elapsed_ms=budget.elapsed_ms
        )
    except ValueError:
        return [], SubtitleProbe(
            status="invalid",
            reason="字幕接口返回的数据无法解析",
            elapsed_ms=budget.elapsed_ms,
        )

    if player.get("code") != 0:
        return [], SubtitleProbe(
            status="inaccessible",
            reason=f"字幕接口返回：{player.get('message', '未知错误')}",
            elapsed_ms=budget.elapsed_ms,
        )

    subtitles = (
        ((player.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    )
    candidates = [sub for sub in subtitles if sub.get("subtitle_url")]
    if not candidates:
        return [], SubtitleProbe(
            status="absent",
            reason="平台没有返回独立字幕轨",
            elapsed_ms=budget.elapsed_ms,
        )

    selected = min(
        candidates,
        key=lambda sub: subtitle_priority(sub.get("lan", ""), _subtitle_kind(sub)),
    )
    url = selected["subtitle_url"]
    if url.startswith("//"):
        url = "https:" + url
    try:
        body = _probe_json(url, budget).get("body") or []
        track = SubtitleTrack(
            language=selected.get("lan", ""),
            kind=_subtitle_kind(selected),
            cues=[
                SubtitleCue(
                    start=float(c["from"]), end=float(c["to"]), text=c["content"]
                )
                for c in body
                if isinstance(c, dict)
                and isinstance(c.get("content"), str)
                and c["content"].strip()
            ],
        )
    except (ProbeDeadlineExceeded, OMRError, OSError) as exc:
        return [], SubtitleProbe(
            status="inaccessible", reason=str(exc), elapsed_ms=budget.elapsed_ms
        )
    except (KeyError, TypeError, ValueError):
        return [], SubtitleProbe(
            status="invalid",
            reason="字幕正文格式无效",
            elapsed_ms=budget.elapsed_ms,
        )

    return [track], probe_for_track(track, duration, budget.elapsed_ms)


def _inaccessible_manifest(original_url, canonical, bvid, reason, budget):
    return ContentManifest(
        platform="bilibili",
        original_url=original_url,
        canonical_url=canonical,
        content_type="video",
        title=f"B站视频 {bvid}",
        subtitle_probe=SubtitleProbe(
            status="inaccessible",
            reason=reason or "无法在探测预算内取得字幕元数据",
            elapsed_ms=budget.elapsed_ms,
        ),
    )
