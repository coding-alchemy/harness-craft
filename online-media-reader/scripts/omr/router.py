# -*- coding: utf-8 -*-
"""平台路由：从 URL 识别平台，不做网络访问。"""

import re
from urllib.parse import urlparse, parse_qs

from .model import UnsupportedURLError


def official_host(host, domain):
    """只接受官方主域名及其子域名，不接受名称相似的后缀域名。"""
    return host == domain or host.endswith("." + domain)


def detect_platform(url):
    """返回平台标识 douyin | bilibili | xiaohongshu；无法识别时抛 UnsupportedURLError。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        raise UnsupportedURLError(url)

    if host == "v.douyin.com":
        return "douyin"

    if official_host(host, "douyin.com"):
        path = urlparse(url).path
        has_video = bool(re.search(r"/video/\d+", path))
        # modal_id 是弹窗视频 ID，出现在任意个人页形态（/user/self、/user/profile/...）
        has_modal = "modal_id" in parse_qs(urlparse(url).query)
        if has_video or has_modal:
            return "douyin"
        raise UnsupportedURLError(url)

    if official_host(host, "bilibili.com") or host == "b23.tv":
        return "bilibili"

    if official_host(host, "xiaohongshu.com") or official_host(
        host, "xhslink.com"
    ):
        return "xiaohongshu"

    raise UnsupportedURLError(url)
