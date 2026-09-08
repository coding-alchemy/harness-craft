# -*- coding: utf-8 -*-
"""通过统一入口 scripts/read.py 验证路由、Markdown 输出合同和临时目录生命周期。

固定样本经 OMR_FIXTURE 环境变量注入，测试不访问真实网络。
"""

import json
import os
import stat
import textwrap
import subprocess
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

from test_video_pipeline import write_fixture  # noqa: E402


def run_entry(url, output, extra_args=None, fixture=None):
    env = dict(os.environ)
    if fixture is None:
        env.pop("OMR_FIXTURE", None)
    elif Path(fixture).is_file():
        env["OMR_FIXTURE"] = str(fixture)
    else:
        env["OMR_FIXTURE"] = str(FIXTURES / fixture)
    # 图文样本的 ocr_text 留空时走真实 OCR 分支；用假 OCR 保持离线与确定性。
    bindir = output.parent / ".fakes"
    bindir.mkdir(exist_ok=True)
    fake_ocr = bindir / "fake-ocr"
    fake_ocr.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            text=$(cat "$1")
            printf '{"text": "%s"}' "$text"
            """
        ),
        encoding="utf-8",
    )
    fake_ocr.chmod(fake_ocr.stat().st_mode | stat.S_IEXEC)
    env["OMR_OCR_BIN"] = str(fake_ocr)
    return subprocess.run(
        [sys.executable, str(ENTRY), url, "--output", str(output)]
        + (extra_args or []),
        capture_output=True,
        text=True,
        env=env,
        cwd=output.parent,
    )


def _dynamic_gallery_fixture(work_root, name):
    """真实形态的图文样本：图片 file:// 可下载、ocr_text 留空交给假 OCR。"""
    img1 = work_root / f"{name}-1.txt"
    img1.write_text("第一张图片的文字", encoding="utf-8")
    img2 = work_root / f"{name}-2.txt"
    img2.write_text("\n", encoding="utf-8")
    base = json.loads((FIXTURES / "xiaohongshu_note.json").read_text(encoding="utf-8"))
    base["image_items"] = [
        {"index": 1, "url": img1.as_uri(), "ocr_text": None},
        {"index": 2, "url": img2.as_uri(), "ocr_text": None},
    ]
    return write_fixture(work_root, f"{name}.json", base)


def test_supported_urls_route_to_platform(work_root):
    cases = [
        ("https://www.bilibili.com/video/BV1sample00", "bilibili_subtitle.json", "bilibili"),
        ("https://b23.tv/abcDEF0", "bilibili_subtitle.json", "bilibili"),
        ("https://www.douyin.com/video/7000000000000000000", "douyin_video.json", "douyin"),
        ("https://v.douyin.com/AbCdEf0/", "douyin_video.json", "douyin"),
        ("https://www.xiaohongshu.com/explore/64sample000000000000sample0", _dynamic_gallery_fixture(work_root, "route-gal"), "xiaohongshu"),
        ("https://www.douyin.com/user/profile/abc?modal_id=7000000000000000000", "douyin_video.json", "douyin"),
    ]
    for url, fixture, platform in cases:
        out = work_root / "out.md"
        result = run_entry(url, out, fixture=fixture)
        assert result.returncode == 0, result.stderr
        text = out.read_text(encoding="utf-8")
        assert platform in text


def test_unsupported_url_fails_without_markdown(work_root):
    out = work_root / "out.md"
    result = run_entry("https://example.com/watch?v=abc", out)
    assert result.returncode != 0
    assert not out.exists()
    assert "不支持" in result.stderr or "不支持" in result.stdout


def test_spoofed_platform_domains_are_rejected(work_root):
    for url in (
        "https://evil-douyin.com/video/7000000000000000000",
        "https://evilbilibili.com/video/BV1sample00",
        "https://notxiaohongshu.com/explore/64abcdef",
    ):
        out = work_root / "out.md"
        result = run_entry(url, out)

        assert result.returncode == 2
        assert json.loads(result.stderr)["stage"] == "routing"
        assert not out.exists()


def test_cli_argument_errors_use_structured_failure_json(work_root):
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
            cwd=work_root,
        )

        assert result.returncode == 2
        assert result.stdout == ""
        assert json.loads(result.stderr) == {
            "status": "error",
            "stage": "routing",
            "error": json.loads(result.stderr)["error"],
            "run_dir": None,
        }


def test_manifest_renders_required_markdown_sections(work_root):
    out = work_root / "out.md"
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


def test_douyin_marks_processing_path(work_root):
    out = work_root / "out.md"
    result = run_entry(
        "https://www.douyin.com/video/7000000000000000000", out, fixture="douyin_video.json"
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：自动字幕" in text


def test_xiaohongshu_renders_ordered_ocr_and_empty_marker(work_root):
    out = work_root / "out.md"
    result = run_entry(
        "https://www.xiaohongshu.com/explore/64sample000000000000sample0",
        out,
        fixture=_dynamic_gallery_fixture(work_root, "render-gal"),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "OCR" in text
    assert text.index("第一张图片的文字") < text.index("第 2 张")
    assert "未识别到文字" in text
    assert "平台摘要" in text
    assert "平台生成的补充摘要文本" in text


def test_reliable_subtitle_renders_continuous_and_timed_transcripts(work_root):
    out = work_root / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00", out, fixture="bilibili_subtitle.json"
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "## 原始字幕\n\n第一句固定样本字幕。第二句固定样本字幕。\n\n" in text
    assert "- [00:00:03 → 00:00:06] 第二句固定样本字幕。" in text
    assert text.index("## 原始字幕") < text.index("## 人工字幕")


def test_xiaohongshu_gallery_omits_continuous_transcript(work_root):
    out = work_root / "out.md"
    result = run_entry(
        "https://www.xiaohongshu.com/explore/64sample000000000000sample0",
        out,
        fixture=_dynamic_gallery_fixture(work_root, "omit-gal"),
    )
    assert result.returncode == 0, result.stderr
    assert "原始字幕" not in out.read_text(encoding="utf-8")


def test_work_dir_cleaned_on_success(work_root):
    out = work_root / "out.md"
    ok = run_entry(
        "https://www.bilibili.com/video/BV1sample00", out, fixture="bilibili_subtitle.json"
    )
    assert ok.returncode == 0, ok.stderr
    payload = json.loads(ok.stdout)
    assert not (Path(payload["run_dir"]) / "work").exists()
