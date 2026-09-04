# -*- coding: utf-8 -*-
"""Markdown 标题保守去重与连续字幕同源渲染。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from omr.model import ContentManifest, ImageItem, SubtitleCue, SubtitleProbe, SubtitleTrack
from omr.render import render_markdown


def manifest(title):
    return ContentManifest(
        platform="bilibili",
        original_url="https://example.test/original",
        canonical_url="https://example.test/canonical",
        content_type="video",
        title=title,
    )


def track(cues, language="zh-CN", kind="manual"):
    return SubtitleTrack(language=language, kind=kind, cues=cues)


def cue(start, end, text):
    return SubtitleCue(start=start, end=end, text=text)


def test_continuous_transcript_joins_chinese_cues_directly():
    item = manifest("示例视频")
    item.subtitle_tracks = [track([cue(0, 2, "第一句。"), cue(2, 4, "第二句。")])]

    text = render_markdown(item)

    assert text.index("## 完整连续字幕") < text.index("## 人工字幕")
    assert "第一句。第二句。" in text


def test_continuous_transcript_space_only_between_ascii_alnum_sides():
    ascii_pair = manifest("示例视频")
    ascii_pair.subtitle_tracks = [
        track([cue(0, 1, "Hello"), cue(1, 2, "world")])
    ]
    zh_to_ascii = manifest("示例视频")
    zh_to_ascii.subtitle_tracks = [
        track([cue(0, 1, "版本"), cue(1, 2, "2.0")])
    ]
    ascii_to_zh = manifest("示例视频")
    ascii_to_zh.subtitle_tracks = [
        track([cue(0, 1, "v1"), cue(1, 2, "发布")])
    ]

    assert "Hello world" in render_markdown(ascii_pair)
    assert "版本2.0" in render_markdown(zh_to_ascii)
    assert "v1发布" in render_markdown(ascii_to_zh)


def test_continuous_transcript_strips_and_folds_internal_newlines():
    zh = manifest("示例视频")
    zh.subtitle_tracks = [
        track([cue(0, 2, "  第一行\n第二行  "), cue(2, 4, "\n第三行\n")])
    ]
    ascii_cue = manifest("示例视频")
    ascii_cue.subtitle_tracks = [track([cue(0, 2, "abc\ndef")])]

    assert "第一行第二行第三行" in render_markdown(zh)
    assert "abc def" in render_markdown(ascii_cue)


def test_continuous_transcript_skips_empty_cues():
    item = manifest("示例视频")
    item.subtitle_tracks = [
        track([cue(0, 1, "正文。"), cue(1, 2, "   "), cue(2, 3, "")])
    ]

    text = render_markdown(item)

    assert "正文。" in text
    assert "## 完整连续字幕\n\n正文。\n\n" in text


def test_continuous_transcript_uses_only_first_track():
    item = manifest("示例视频")
    item.subtitle_tracks = [
        track([cue(0, 1, "主轨句子。")]),
        track([cue(0, 1, "核验轨句子。")], kind="auto"),
    ]

    text = render_markdown(item)

    assert text.count("## 完整连续字幕") == 1
    assert "## 完整连续字幕\n\n主轨句子。\n\n" in text


def test_image_gallery_omits_continuous_transcript():
    item = manifest("图文笔记")
    item.content_type = "image_gallery"
    item.image_items = [ImageItem(index=1, url="https://example.test/1.jpg", ocr_text="图片文字")]

    text = render_markdown(item)

    assert "完整连续字幕" not in text
    assert "图片文字" in text


def test_rerender_after_cue_edit_updates_both_transcripts():
    item = manifest("示例视频")
    item.subtitle_tracks = [track([cue(0, 2, "原始转写")])]
    assert "原始转写" in render_markdown(item)

    item.subtitle_tracks[0].cues[0].text = "画面纠正文字"
    after = render_markdown(item)

    assert "原始转写" not in after
    assert "## 完整连续字幕\n\n画面纠正文字\n\n" in after
    assert "- [00:00:00 → 00:00:02] 画面纠正文字" in after


def test_video_without_usable_track_text_omits_continuous_section():
    item = manifest("无字幕视频")
    item.subtitle_tracks = [track([cue(0, 1, "   ")])]

    assert "完整连续字幕" not in render_markdown(item)


def test_exact_repeated_title_half_is_rendered_once():
    text = render_markdown(manifest("宏观策略周报宏观策略周报"))
    assert text.startswith("# 宏观策略周报\n")
    actual_case = "🤔 舆情监测系统TOP10有哪些？ 🤔 舆情监测系统TOP10有哪些？"
    assert render_markdown(manifest(actual_case)).startswith(
        "# 🤔 舆情监测系统TOP10有哪些？\n"
    )


def test_non_exact_and_short_repetition_are_unchanged():
    assert render_markdown(manifest("宏观策略周报宏观策略日报")).startswith(
        "# 宏观策略周报宏观策略日报\n"
    )
    assert render_markdown(manifest("哈哈")).startswith("# 哈哈\n")
    assert render_markdown(manifest("  宏观策略周报  ")).startswith(
        "#   宏观策略周报  \n"
    )


def test_inaccessible_online_probe_reason_is_reported():
    item = manifest("B站视频")
    item.subtitle_probe = SubtitleProbe(
        status="inaccessible",
        reason="B站接口访问失败。访问失败不等同于确认无字幕。",
    )

    text = render_markdown(item)

    assert (
        "> 在线字幕探测不可访问：B站接口访问失败。访问失败不等同于确认无字幕。"
        in text
    )
