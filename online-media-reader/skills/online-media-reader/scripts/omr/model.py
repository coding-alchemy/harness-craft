# -*- coding: utf-8 -*-
"""内部内容清单与文字来源模型。

清单是适配器与渲染器之间的内部边界，不发布稳定 JSON API。
"""

from dataclasses import dataclass, field
from typing import List, Optional

PLATFORMS = ("douyin", "bilibili", "xiaohongshu")

SUBTITLE_KIND_LABELS = {
    "manual": "人工字幕",
    "auto": "自动字幕",
    "asr": "语音转写（ASR）",
}


class OMRError(Exception):
    """面向用户的失败：message 直接进入 stderr。"""

    def __init__(self, message, exit_code=1):
        super().__init__(message)
        self.exit_code = exit_code


class WorkspaceFinalizationError(OMRError):
    """运行结果已生成，但工作目录清理或终态记录失败。"""


class UnsupportedURLError(OMRError):
    def __init__(self, url):
        super().__init__(
            f"不支持的 URL：{url}。仅支持抖音、B站（bilibili.com / b23.tv）"
            "和小红书（xiaohongshu.com / xhslink.com）的公开单条内容链接。",
            exit_code=2,
        )


class AccessRestrictedError(OMRError):
    """平台已明确返回登录、验证、私密或其他访问限制。"""


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


@dataclass
class SubtitleTrack:
    language: str
    kind: str  # manual | auto
    cues: List[SubtitleCue] = field(default_factory=list)

    def label(self):
        return SUBTITLE_KIND_LABELS.get(self.kind, self.kind)


@dataclass
class SubtitleProbe:
    status: str = ""
    reason: str = ""
    elapsed_ms: int = 0


@dataclass
class ImageItem:
    index: int
    url: str
    ocr_text: Optional[str] = None


@dataclass(frozen=True)
class MediaSources:
    """经页面验证的直连媒体来源。"""

    audio: Optional[str] = None
    video: Optional[str] = None
    review_video: Optional[str] = None
    muxed: Optional[str] = None
    referer: Optional[str] = None

    @property
    def review_url(self):
        return self.review_video or self.muxed or self.video


@dataclass(frozen=True)
class ReviewState:
    """画面复核状态及其可选目录和说明。"""

    status: str = "not_required"
    path: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self):
        if self.status not in {"not_required", "pending", "reviewed", "unavailable"}:
            raise ValueError(f"未知的画面复核状态：{self.status}")

    @classmethod
    def from_dict(cls, data):
        return cls(
            status=data.get("review_status") or "not_required",
            path=data.get("review_path"),
            reason=data.get("review_reason"),
        )

    @classmethod
    def pending(cls, path):
        return cls(status="pending", path=str(path))

    @classmethod
    def reviewed(cls, path, reason=None):
        return cls(status="reviewed", path=str(path), reason=reason)

    @classmethod
    def unavailable(cls, reason, path=None):
        return cls(
            status="unavailable", path=str(path) if path else None, reason=str(reason)
        )

    @property
    def required(self):
        return self.status == "pending"

    def to_dict(self):
        payload = {"review_status": self.status}
        if self.path is not None:
            payload["review_path"] = self.path
        if self.reason is not None:
            payload["review_reason"] = self.reason
        return payload


@dataclass
class ContentManifest:
    platform: str
    original_url: str
    canonical_url: str
    content_type: str  # video | image_gallery
    title: str
    author: str = ""
    published_at: str = ""
    duration: Optional[float] = None
    subtitle_tracks: List[SubtitleTrack] = field(default_factory=list)
    subtitle_probe: SubtitleProbe = field(default_factory=SubtitleProbe)
    media_items: List[dict] = field(default_factory=list)
    image_items: List[ImageItem] = field(default_factory=list)
    summary: Optional[str] = None
    # 处理路径：实际采用的文字来源（人工字幕 / 自动字幕 / ASR / OCR / 无）
    processing_path: str = ""
    review: ReviewState = field(default_factory=ReviewState)
    # 匿名会话 Cookie 文件（位于临时工作目录，用后随目录清理）
    cookie_file: Optional[str] = None
    media_sources: MediaSources = field(default_factory=MediaSources)

    @classmethod
    def from_dict(cls, data):
        probe = data.get("subtitle_probe") or {}
        tracks = [
            SubtitleTrack(
                language=t["language"],
                kind=t["kind"],
                cues=[
                    SubtitleCue(start=c["start"], end=c["end"], text=c["text"])
                    for c in t.get("cues", [])
                ],
            )
            for t in data.get("subtitle_tracks", [])
        ]
        images = [
            ImageItem(index=i["index"], url=i["url"], ocr_text=i.get("ocr_text"))
            for i in data.get("image_items", [])
        ]
        return cls(
            platform=data["platform"],
            original_url=data["original_url"],
            canonical_url=data["canonical_url"],
            content_type=data["content_type"],
            title=data["title"],
            author=data.get("author", ""),
            published_at=data.get("published_at", ""),
            duration=data.get("duration"),
            subtitle_tracks=tracks,
            subtitle_probe=SubtitleProbe(
                status=probe.get("status", ""),
                reason=probe.get("reason", ""),
                elapsed_ms=int(probe.get("elapsed_ms", 0)),
            ),
            media_items=data.get("media_items", []),
            image_items=images,
            summary=data.get("summary"),
            processing_path=data.get("processing_path", ""),
            review=ReviewState.from_dict(data),
            cookie_file=data.get("cookie_file"),
        )

    def to_dict(self):
        """重渲染所需的内部快照；复核输入用它保存内容状态。"""
        payload = {
            "platform": self.platform,
            "original_url": self.original_url,
            "canonical_url": self.canonical_url,
            "content_type": self.content_type,
            "title": self.title,
            "author": self.author,
            "published_at": self.published_at,
            "duration": self.duration,
            "subtitle_tracks": [
                {
                    "language": track.language,
                    "kind": track.kind,
                    "cues": [
                        {"start": cue.start, "end": cue.end, "text": cue.text}
                        for cue in track.cues
                    ],
                }
                for track in self.subtitle_tracks
            ],
            "subtitle_probe": {
                "status": self.subtitle_probe.status,
                "reason": self.subtitle_probe.reason,
                "elapsed_ms": self.subtitle_probe.elapsed_ms,
            },
            "media_items": self.media_items,
            "image_items": [
                {"index": image.index, "url": image.url, "ocr_text": image.ocr_text}
                for image in self.image_items
            ],
            "summary": self.summary,
            "processing_path": self.processing_path,
        }
        payload.update(self.review.to_dict())
        return payload
