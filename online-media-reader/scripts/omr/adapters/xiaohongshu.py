# -*- coding: utf-8 -*-
"""小红书适配器：区分视频与图文笔记，读取公开元数据与有序图片清单。

直连 SSR 拿不到笔记数据时，用匿名浏览器上下文渲染页面读取
window.__INITIAL_STATE__。登录、验证或私密内容一律失败关闭。
"""

import datetime
import re
from urllib.parse import urlparse, parse_qs

from .. import browser_session
from ..model import (
    AccessRestrictedError,
    ContentManifest,
    ImageItem,
    OMRError,
    SubtitleProbe,
)
from ..platform_http import fail_closed, fetch_text, request
from ..router import official_host
from ..subtitles import ProbeDeadlineExceeded, SubtitleProbeBudget

_FAIL_MARKERS = ("扫码登录", "访问验证", "笔记不存在", "仅登录后可见", "审核中")
_STATE_PATTERN = r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>"

# 页面内提取表达式：只挑需要的字段，避免 Vue 响应式对象的循环引用
_EXTRACT_NOTE = """() => {
    const body = (document.body && document.body.innerText) || '';
    for (const marker of ['扫码登录', '访问验证', '笔记不存在', '仅登录后可见', '审核中']) {
        if (body.includes(marker)) return {__accessRestriction: marker};
    }
    const s = window.__INITIAL_STATE__;
    if (!s || !s.note || !s.note.noteDetailMap) return null;
    const out = {};
    for (const [id, nd] of Object.entries(s.note.noteDetailMap)) {
        const n = (nd && nd.note) || {};
        out[id] = {
            type: n.type || null,
            title: n.title || null,
            desc: n.desc || null,
            time: n.time || null,
            nickname: (n.user && n.user.nickname) || null,
            imageUrls: (n.imageList || []).map(im =>
                (im.infoList && im.infoList.length
                    ? im.infoList[im.infoList.length - 1].url : null) || im.url || null),
        };
    }
    return out;
}"""


def normalize_url(url, budget=None):
    """展开 xhslink.com 短链，识别笔记 ID；保留必要的 xsec_token。"""
    parsed = urlparse(url)
    if parsed.hostname in ("xhslink.com", "www.xhslink.com"):
        import http.client

        from urllib.request import build_opener

        head = request(url)
        head.method = "HEAD"
        timeout = budget.remaining() if budget else 30
        with build_opener().open(head, timeout=timeout) as resp:
            url = resp.geturl()
        parsed = urlparse(url)
    if not official_host((parsed.hostname or "").lower(), "xiaohongshu.com"):
        raise OMRError(f"小红书链接展开结果不是 xiaohongshu.com：{url}", exit_code=4)
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]+)", parsed.path)
    if not m:
        raise OMRError(f"无法从小红书链接识别笔记 ID：{url}", exit_code=4)
    note_id = m.group(1)
    # xsec_token / xsec_source 是访问凭证，规范化时必须保留
    canonical = f"https://www.xiaohongshu.com/explore/{note_id}"
    if parsed.query:
        canonical += f"?{parsed.query}"
    return note_id, canonical


def parse_initial_state(html):
    """提取页面 window.__INITIAL_STATE__；受限制内容失败关闭。"""
    fail_closed(_FAIL_MARKERS, html, "小红书")
    m = re.search(_STATE_PATTERN, html, re.S)
    if not m:
        raise OMRError("无法从小红书页面提取数据，页面结构可能已变化。", exit_code=4)
    import json

    raw = re.sub(r":\s*undefined\b", ": null", m.group(1))
    try:
        return json.loads(raw)
    except ValueError:
        raise OMRError("小红书页面数据解析失败，页面结构可能已变化。", exit_code=4)


def _note_from_state(state, note_id):
    note_map = ((state or {}).get("note") or {}).get("noteDetailMap") or {}
    return ((note_map.get(note_id) or {}).get("note")) or None


def _image_urls(note):
    """统一浏览器投影字段与直连 SSR 的原始 imageList。"""
    projected = note.get("imageUrls")
    if projected is not None:
        return [url for url in projected if url]

    urls = []
    for image in note.get("imageList") or []:
        if not isinstance(image, dict):
            continue
        info_list = image.get("infoList") or []
        last_info = info_list[-1] if info_list else {}
        url = (
            last_info.get("url") if isinstance(last_info, dict) else None
        ) or image.get("url")
        if url:
            urls.append(url)
    return urls


def fetch(url, workdir, probe_only=False):
    budget = SubtitleProbeBudget() if probe_only else None
    try:
        note_id, canonical = normalize_url(url, budget=budget)
    except ProbeDeadlineExceeded as exc:
        return _probe_inaccessible(url, url, "unknown", str(exc), budget)

    note = None
    try:
        timeout = budget.remaining() if budget else 30
        html = fetch_text(canonical, timeout=timeout)
        note = _note_from_state(parse_initial_state(html), note_id)
    except ProbeDeadlineExceeded as exc:
        return _probe_inaccessible(url, canonical, note_id, str(exc), budget)
    except AccessRestrictedError:
        raise
    except (OMRError, OSError, TimeoutError):
        note = None  # 直连 SSR 无数据，改用匿名浏览器渲染

    if not note:
        try:
            timeout_ms = (
                max(1, int(budget.remaining() * 1000))
                if budget
                else 50000
            )
            rendered = browser_session.render_state(
                canonical, _EXTRACT_NOTE, timeout_ms=timeout_ms
            )
        except ProbeDeadlineExceeded as exc:
            return _probe_inaccessible(
                url, canonical, note_id, str(exc), budget
            )
        except OMRError as exc:
            if probe_only:
                return _probe_inaccessible(
                    url, canonical, note_id, str(exc), budget
                )
            raise
        restriction = (rendered or {}).get("__accessRestriction")
        if restriction:
            raise AccessRestrictedError(
                f"小红书页面要求：{restriction}。受限制内容不支持自动处理，已停止。",
                exit_code=4,
            )
        note = (rendered or {}).get(note_id) or None
    if not note:
        raise OMRError(
            "小红书页面未返回笔记信息，可能需要登录或内容非公开。已停止。", exit_code=4
        )

    is_video = note.get("type") == "video"
    desc_lines = (note.get("desc") or "").splitlines()
    title = (
        note.get("title")
        or (desc_lines[0] if desc_lines else "")
        or f"小红书笔记 {note_id}"
    )
    ts = note.get("time")
    image_items = [
        ImageItem(index=i, url=u)
        for i, u in enumerate(_image_urls(note), start=1)
    ]
    if not is_video and not image_items:
        raise OMRError(
            "小红书图文页面未返回图片，页面结构可能已变化。", exit_code=4
        )

    return ContentManifest(
        platform="xiaohongshu",
        original_url=url,
        canonical_url=canonical,
        content_type="video" if is_video else "image_gallery",
        title=title,
        author=(
            note.get("nickname")
            or (note.get("user") or {}).get("nickname")
            or ""
        ),
        published_at=datetime.date.fromtimestamp(int(ts) / 1000).isoformat()
        if ts else "",
        duration=None,
        subtitle_tracks=[],  # 小红书无公开字幕接口，视频由共用 ASR 流程兜底
        subtitle_probe=SubtitleProbe(
            status="absent",
            reason="平台没有公开字幕轨",
            elapsed_ms=budget.elapsed_ms if budget else 0,
        ),
        image_items=image_items,
    )


def _probe_inaccessible(original_url, canonical, note_id, reason, budget):
    return ContentManifest(
        platform="xiaohongshu",
        original_url=original_url,
        canonical_url=canonical,
        content_type="video",
        title=f"小红书笔记 {note_id}",
        subtitle_probe=SubtitleProbe(
            status="inaccessible",
            reason=reason or "无法在探测预算内取得内容元数据",
            elapsed_ms=budget.elapsed_ms if budget else 0,
        ),
    )
