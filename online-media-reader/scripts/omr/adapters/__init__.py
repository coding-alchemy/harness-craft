# -*- coding: utf-8 -*-
"""固定三平台适配器入口。"""

import json
import os

from ..model import ContentManifest, OMRError
from . import bilibili, douyin, xiaohongshu


def fetch_manifest(platform, url, workdir, probe_only=False):
    """取得平台内容清单。OMR_FIXTURE 指向固定样本 JSON 时用于测试。"""
    fixture = os.environ.get("OMR_FIXTURE")
    if fixture:
        with open(fixture, encoding="utf-8") as f:
            return ContentManifest.from_dict(json.load(f))
    if platform == "bilibili":
        return bilibili.fetch(url, workdir, probe_only=probe_only)
    if platform == "douyin":
        return douyin.fetch(url, workdir, probe_only=probe_only)
    if platform == "xiaohongshu":
        return xiaohongshu.fetch(url, workdir, probe_only=probe_only)
    raise OMRError(f"平台 {platform} 适配器尚未实现。", exit_code=3)
