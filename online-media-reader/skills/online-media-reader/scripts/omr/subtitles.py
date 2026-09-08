# -*- coding: utf-8 -*-
"""字幕质量评估、来源选择与有界在线探测。"""

import math
import time
from urllib.error import HTTPError, URLError

from .model import SubtitleProbe, SubtitleTrack

# 覆盖率低于该阈值或存在大缺口时判定不可靠，触发转写
MIN_COVERAGE = 0.8
MAX_GAP_SECONDS = 30.0
DURATION_TOLERANCE_SECONDS = 2.0
MIN_TEXT_CHARACTERS = 4
TEXT_SECONDS_PER_CHARACTER = 30
SUBTITLE_PROBE_SECONDS = 30


class ProbeDeadlineExceeded(Exception):
    """字幕探测已用完共享墙钟预算。"""


class SubtitleProbeBudget:
    """字幕专用请求共享的单一截止时间。"""

    def __init__(self, seconds=SUBTITLE_PROBE_SECONDS, clock=None):
        self.seconds = seconds
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._deadline = self._started + seconds

    def remaining(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise ProbeDeadlineExceeded(
                f"字幕探测已达到 {self.seconds:g} 秒总预算"
            )
        return remaining

    @property
    def elapsed_ms(self):
        elapsed = max(self._clock() - self._started, 0)
        return int(round(elapsed * 1000))


def run_probe_request(operation, budget):
    """在共享预算内执行请求；瞬时网络故障最多重试一次。"""
    last_error = None
    for _attempt in range(2):
        timeout = budget.remaining()
        try:
            return operation(timeout)
        except HTTPError as exc:
            if not 500 <= exc.code < 600:
                raise
            last_error = exc
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
    raise last_error


def subtitle_priority(language, kind):
    """中文人工 → 中文自动 → 默认人工 → 默认自动。"""
    normalized = language.lower().replace("_", "-")
    if normalized.startswith("ai-"):
        normalized = normalized[3:]
    is_zh = normalized.startswith("zh")
    order = {
        (True, "manual"): 0,
        (True, "auto"): 1,
        (False, "manual"): 2,
        (False, "auto"): 3,
    }
    return order.get((is_zh, kind), 4)


def assess_track(track, duration):
    """返回 (可靠, 问题描述列表)；时长未知时仍检查内部大缺口。"""
    issues = []
    cues = track.cues
    text_cues = [
        cue
        for cue in cues
        if isinstance(cue.text, str) and cue.text.strip()
    ]
    if not text_cues:
        return False, ["字幕文本为空"]

    previous_start = None
    for cue in cues:
        if cue.end < cue.start or (
            previous_start is not None and cue.start < previous_start
        ):
            issues.append("时间戳未递增或区间非法")
        previous_start = cue.start

    has_duration = duration is not None and duration > 0
    minimum_text = (
        max(
            MIN_TEXT_CHARACTERS,
            math.ceil(duration / TEXT_SECONDS_PER_CHARACTER),
        )
        if has_duration
        else MIN_TEXT_CHARACTERS
    )
    text_size = sum(len("".join(cue.text.split())) for cue in text_cues)
    if text_size < minimum_text:
        issues.append(f"字幕文本少于 {minimum_text} 个字符")

    if has_duration and any(
        cue.start < -DURATION_TOLERANCE_SECONDS
        or cue.end > duration + DURATION_TOLERANCE_SECONDS
        for cue in text_cues
    ):
        issues.append("字幕时间范围超出视频时长")

    intervals = []
    for cue in text_cues:
        start = (
            max(min(cue.start, duration), 0)
            if has_duration
            else max(cue.start, 0)
        )
        end = (
            max(min(cue.end, duration), 0)
            if has_duration
            else max(cue.end, 0)
        )
        if end > start:
            intervals.append((start, end))

    merged = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    if has_duration:
        covered = sum(end - start for start, end in merged)
        coverage = covered / duration
        if coverage < MIN_COVERAGE:
            issues.append(f"覆盖率 {coverage:.0%} 低于 {MIN_COVERAGE:.0%}")

    gap_limit = (
        max(MAX_GAP_SECONDS, 0.1 * duration)
        if has_duration
        else MAX_GAP_SECONDS
    )
    prev_end = 0.0 if has_duration else (merged[0][1] if merged else 0.0)
    gap_intervals = merged if has_duration else merged[1:]
    for start, end in gap_intervals:
        gap = start - prev_end
        if gap > gap_limit:
            issues.append(f"存在 {gap:.0f} 秒覆盖缺口")
        prev_end = end
    if has_duration:
        tail_gap = duration - prev_end
        if tail_gap > gap_limit:
            issues.append(f"存在 {tail_gap:.0f} 秒尾部覆盖缺口")

    return (not issues), issues


def choose_track(tracks):
    """按 中文人工 → 中文自动 → 默认人工 → 默认自动 选择字幕轨。"""
    candidates = [track for track in tracks if track.cues]
    return min(
        candidates,
        key=lambda track: subtitle_priority(track.language, track.kind),
        default=None,
    )


def probe_for_track(track, duration, elapsed_ms):
    """把已下载字幕归一为可供入口决策的探测结果。"""
    reliable, issues = assess_track(track, duration)
    if reliable:
        return SubtitleProbe(
            status="usable",
            reason="字幕已下载并通过质量检查",
            elapsed_ms=elapsed_ms,
        )
    return SubtitleProbe(
        status="invalid",
        reason="；".join(issues) or "字幕未通过质量检查",
        elapsed_ms=elapsed_ms,
    )


def finalize_probe(manifest):
    """为固定样本或旧清单补齐字幕探测结果。"""
    if manifest.subtitle_probe.status:
        return manifest.subtitle_probe
    if manifest.content_type != "video":
        manifest.subtitle_probe = SubtitleProbe(
            status="absent", reason="该内容不是视频，不使用字幕"
        )
        return manifest.subtitle_probe
    track = choose_track(manifest.subtitle_tracks)
    if track is None:
        manifest.subtitle_probe = SubtitleProbe(
            status="absent", reason="平台没有返回独立字幕轨"
        )
    else:
        manifest.subtitle_probe = probe_for_track(track, manifest.duration, 0)
    return manifest.subtitle_probe


def parse_webvtt(text):
    """解析 WebVTT/SRT 字幕文本为 Cue 列表；空字幕返回 []。"""
    import re

    from .model import SubtitleCue

    def to_seconds(stamp):
        stamp = stamp.strip().replace(",", ".")
        parts = stamp.split(":")
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds

    cues = []
    block = []
    for line in text.splitlines() + [""]:
        if line.strip():
            block.append(line)
            continue
        if block:
            m = re.search(
                r"(\d[\d:.]+)\s*-->\s*(\d[\d:.]+)", "\n".join(block)
            )
            if m:
                timing_index = next(
                    i for i, line in enumerate(block) if "-->" in line
                )
                payload = block[timing_index + 1:]
                text_payload = " ".join(payload).strip()
                if text_payload:
                    cues.append(
                        SubtitleCue(
                            start=to_seconds(m.group(1)),
                            end=to_seconds(m.group(2)),
                            text=text_payload,
                        )
                    )
            block = []
    return cues


def track_from_asr_segments(segments):
    """把 faster-whisper 段落转换为 ASR 字幕轨。"""
    from .model import SubtitleCue

    return SubtitleTrack(
        language="asr",
        kind="asr",
        cues=[
            SubtitleCue(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s["text"].strip(),
            )
            for s in segments
            if isinstance(s.get("text"), str) and s["text"].strip()
        ],
    )
