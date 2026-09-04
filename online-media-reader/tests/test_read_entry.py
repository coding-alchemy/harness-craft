# -*- coding: utf-8 -*-
"""通过统一入口 scripts/read.py 验证路由、Markdown 输出合同和临时目录生命周期。

固定样本经 OMR_FIXTURE 环境变量注入，测试不访问真实网络。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_entry(url, output, extra_args=None, fixture=None):
    env = dict(os.environ)
    if fixture is None:
        env.pop("OMR_FIXTURE", None)
    else:
        env["OMR_FIXTURE"] = str(FIXTURES / fixture)
    return subprocess.run(
        [sys.executable, str(ENTRY), url, "--output", str(output)]
        + (extra_args or []),
        capture_output=True,
        text=True,
        env=env,
        cwd=output.parent,
    )


def test_supported_urls_route_to_platform(tmp_path):
    cases = [
        ("https://www.bilibili.com/video/BV1sample00", "bilibili_subtitle.json", "bilibili"),
        ("https://b23.tv/abcDEF0", "bilibili_subtitle.json", "bilibili"),
        ("https://www.douyin.com/video/7000000000000000000", "douyin_video.json", "douyin"),
        ("https://v.douyin.com/AbCdEf0/", "douyin_video.json", "douyin"),
        ("https://www.xiaohongshu.com/explore/64sample000000000000sample0", "xiaohongshu_note.json", "xiaohongshu"),
        ("https://www.douyin.com/user/profile/abc?modal_id=7000000000000000000", "douyin_video.json", "douyin"),
    ]
    for url, fixture, platform in cases:
        out = tmp_path / "out.md"
        result = run_entry(url, out, fixture=fixture)
        assert result.returncode == 0, result.stderr
        text = out.read_text(encoding="utf-8")
        assert platform in text


def test_unsupported_url_fails_without_markdown(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry("https://example.com/watch?v=abc", out)
    assert result.returncode != 0
    assert not out.exists()
    assert "不支持" in result.stderr or "不支持" in result.stdout


def test_spoofed_platform_domains_are_rejected(tmp_path):
    for url in (
        "https://evil-douyin.com/video/7000000000000000000",
        "https://evilbilibili.com/video/BV1sample00",
        "https://notxiaohongshu.com/explore/64abcdef",
    ):
        out = tmp_path / "out.md"
        result = run_entry(url, out)

        assert result.returncode == 2
        assert json.loads(result.stderr)["stage"] == "routing"
        assert not out.exists()


def test_cli_argument_errors_use_structured_failure_json(tmp_path):
    env = dict(os.environ)
    env.pop("OMR_FIXTURE", None)
    cases = [
        [],
        ["https://www.bilibili.com/video/BV1sample00", "--unknown-option"],
    ]

    for args in cases:
        result = subprocess.run(
            [sys.executable, str(ENTRY), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
        )

        assert result.returncode == 2
        assert result.stdout == ""
        assert json.loads(result.stderr) == {
            "status": "error",
            "stage": "routing",
            "error": json.loads(result.stderr)["error"],
            "run_dir": None,
        }


def test_manifest_renders_required_markdown_sections(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00", out, fixture="bilibili_subtitle.json"
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "# 固定样本：示例视频标题" in text
    assert "- 平台：bilibili" in text
    assert "- 内容类型：video" in text
    assert "- 原始 URL：https://www.bilibili.com/video/BV1sample00" in text
    assert "- 规范 URL：https://www.bilibili.com/video/BV1sample00" in text
    assert "- 作者：示例UP主" in text
    assert "- 发布时间：2026-08-01" in text
    assert "人工字幕" in text
    assert "第一句固定样本字幕。" in text
    assert "00:00:00" in text  # 字幕时间戳


def test_douyin_marks_processing_path(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000000", out, fixture="douyin_video.json"
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：自动字幕" in text


def test_xiaohongshu_renders_ordered_ocr_and_empty_marker(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.xiaohongshu.com/explore/64sample000000000000sample0",
        out,
        fixture="xiaohongshu_note.json",
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "OCR" in text
    assert text.index("第一张图片的文字") < text.index("第 2 张")
    assert "未识别到文字" in text
    assert "平台摘要" in text
    assert "平台生成的补充摘要文本" in text


def test_reliable_subtitle_renders_continuous_and_timed_transcripts(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00", out, fixture="bilibili_subtitle.json"
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "## 完整连续字幕\n\n第一句固定样本字幕。第二句固定样本字幕。\n\n" in text
    assert "- [00:00:03 → 00:00:06] 第二句固定样本字幕。" in text
    assert text.index("## 完整连续字幕") < text.index("## 人工字幕")


def test_xiaohongshu_gallery_omits_continuous_transcript(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.xiaohongshu.com/explore/64sample000000000000sample0",
        out,
        fixture="xiaohongshu_note.json",
    )
    assert result.returncode == 0, result.stderr
    assert "完整连续字幕" not in out.read_text(encoding="utf-8")


def test_work_dir_cleaned_on_success(tmp_path):
    out = tmp_path / "out.md"
    ok = run_entry(
        "https://www.bilibili.com/video/BV1sample00", out, fixture="bilibili_subtitle.json"
    )
    assert ok.returncode == 0, ok.stderr
    payload = json.loads(ok.stdout)
    assert not (Path(payload["run_dir"]) / "work").exists()
