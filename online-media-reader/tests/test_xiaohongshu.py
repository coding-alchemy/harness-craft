# -*- coding: utf-8 -*-
"""Ticket 04：小红书图片 OCR 顺序、空结果、视频共用管线与依赖分支隔离。

图片用 file:// 本地固定样本，OCR 用假命令替换；不访问真实网络。
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = MODULE_DIR / "scripts"
ENTRY = SCRIPTS / "read.py"

sys.path.insert(0, str(SCRIPTS))

from omr.adapters import xiaohongshu as xhs_adapter  # noqa: E402
from omr.model import OMRError  # noqa: E402
from test_video_pipeline import run_entry, calls  # noqa: E402

VIDEO_FIXTURE = {
    "platform": "xiaohongshu",
    "original_url": "https://www.xiaohongshu.com/explore/65video000000000000vide0",
    "canonical_url": "https://www.xiaohongshu.com/explore/65video000000000000vide0",
    "content_type": "video",
    "title": "固定样本：小红书视频",
    "author": "示例博主",
    "published_at": "2026-08-20",
    "duration": 10,
    "subtitle_tracks": [],
    "media_items": [],
    "image_items": [],
    "summary": None,
}


def gallery_fixture(tmp_path):
    img1 = tmp_path / "img1.txt"
    img1.write_text("第一张图片 中英文 OCR 文本", encoding="utf-8")
    img2 = tmp_path / "img2.txt"
    img2.write_text("\n", encoding="utf-8")
    return {
        "platform": "xiaohongshu",
        "original_url": "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
        "canonical_url": "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
        "content_type": "image_gallery",
        "title": "固定样本：小红书图文",
        "author": "示例博主",
        "published_at": "2026-08-21",
        "duration": None,
        "subtitle_tracks": [],
        "media_items": [],
        "image_items": [
            {"index": 1, "url": img1.as_uri()},
            {"index": 2, "url": img2.as_uri()},
        ],
        "summary": None,
    }


def test_gallery_ocr_in_order_with_empty_marker(tmp_path):
    fixture = tmp_path / "gallery.json"
    fixture.write_text(json.dumps(gallery_fixture(tmp_path), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
        out,
        tmp_path,
        fixture=str(fixture),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：图片 OCR" in text
    assert "### 第 1 张" in text and "### 第 2 张" in text
    assert text.index("第 1 张") < text.index("第 2 张")
    assert "第一张图片 中英文 OCR 文本" in text
    assert "未识别到文字" in text
    # 不包含画面描述类小节
    assert "画面" not in text


def test_video_uses_shared_asr_without_ocr_dependency(tmp_path):
    fixture = tmp_path / "video.json"
    fixture.write_text(json.dumps(VIDEO_FIXTURE, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    env_result = run_entry(
        "https://www.xiaohongshu.com/explore/65video000000000000vide0",
        out,
        tmp_path,
        fixture=str(fixture),
    )
    assert env_result.returncode == 0, env_result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    assert "转写第一句。" in text
    # 视频分支不需要 OCR：OCR 命令未被调用
    assert not any(c.startswith("ocr") for c in calls(tmp_path))


def test_missing_paddleocr_fails_image_branch_only(tmp_path):
    fixture = tmp_path / "gallery.json"
    fixture.write_text(json.dumps(gallery_fixture(tmp_path), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    # 不提供假 OCR（OMR_OCR_BIN 未设置，宿主机也无 paddleocr 时失败并指出能力）
    env = dict(os.environ)
    env["OMR_FIXTURE"] = str(fixture)
    env.pop("OMR_OCR_BIN", None)
    from test_video_pipeline import make_fakes
    bindir = make_fakes(tmp_path)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["OMR_WHISPER_BIN"] = str(bindir / "fake-whisper")
    env["OMR_CALLLOG"] = str(tmp_path / "calls.log")
    result = subprocess.run(
        [sys.executable, str(ENTRY),
         "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
         "--output", str(out)],
        capture_output=True, text=True, env=env,
        cwd=tmp_path,
    )
    try:
        import paddleocr  # noqa: F401
        installed = True
    except ImportError:
        installed = False
    if not installed:
        assert result.returncode == 3
        assert "PaddleOCR" in result.stderr


def test_initial_state_fail_closed_on_restrictions():
    for marker in ("扫码登录", "访问验证", "笔记不存在"):
        html = f"<html><body>{marker}</body></html>"
        try:
            xhs_adapter.parse_initial_state(html)
        except OMRError as exc:
            assert marker in str(exc) or "无法访问" in str(exc)
        else:
            raise AssertionError(f"含 {marker} 的页面应失败关闭")


def test_ssr_image_list_maps_to_ordered_image_items(monkeypatch, tmp_path):
    note_id = "65abcdef0123456789abcdef"
    state = {
        "note": {
            "noteDetailMap": {
                note_id: {
                    "note": {
                        "type": "normal",
                        "title": "SSR 图文",
                        "user": {"nickname": "SSR 作者"},
                        "imageList": [
                            {
                                "url": "https://cdn/low-1.webp",
                                "infoList": [
                                    {"url": "https://cdn/high-1.webp"}
                                ],
                            },
                            {"url": "https://cdn/image-2.webp"},
                        ],
                    }
                }
            }
        }
    }
    html = (
        "<script>window.__INITIAL_STATE__ = "
        + json.dumps(state)
        + "</script>"
    )
    monkeypatch.setattr(
        xhs_adapter, "fetch_text", lambda _url, timeout=30: html
    )
    monkeypatch.setattr(
        xhs_adapter.browser_session,
        "render_state",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("SSR 已有数据时不应启动浏览器")
        ),
    )

    manifest = xhs_adapter.fetch(
        f"https://www.xiaohongshu.com/explore/{note_id}", tmp_path
    )

    assert [item.index for item in manifest.image_items] == [1, 2]
    assert [item.url for item in manifest.image_items] == [
        "https://cdn/high-1.webp",
        "https://cdn/image-2.webp",
    ]
    assert manifest.author == "SSR 作者"


def test_image_gallery_without_images_is_reported_as_extraction_failure(
    monkeypatch, tmp_path
):
    note_id = "65abcdef0123456789abcdea"
    state = {
        "note": {
            "noteDetailMap": {
                note_id: {"note": {"type": "normal", "title": "空图文"}}
            }
        }
    }
    html = (
        "<script>window.__INITIAL_STATE__ = "
        + json.dumps(state)
        + "</script>"
    )
    monkeypatch.setattr(
        xhs_adapter, "fetch_text", lambda _url, timeout=30: html
    )

    with pytest.raises(OMRError, match="未返回图片"):
        xhs_adapter.fetch(
            f"https://www.xiaohongshu.com/explore/{note_id}", tmp_path
        )


def test_entry_does_not_render_after_restriction(monkeypatch, tmp_path):
    import read as read_entry

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OMR_FIXTURE", raising=False)
    monkeypatch.setattr(
        xhs_adapter,
        "fetch_text",
        lambda url, timeout=30: "<html><body>访问验证</body></html>",
    )

    def unexpected_render(*args):
        raise AssertionError("识别到访问限制后不应启动浏览器重试")

    monkeypatch.setattr(xhs_adapter.browser_session, "render_state", unexpected_render)

    out = tmp_path / "restricted.md"
    result = read_entry.main(
        [
            "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
            "--output",
            str(out),
        ]
    )

    assert result == 4
    assert not out.exists()


def test_browser_fallback_fails_closed_when_rendered_page_requires_login(
    monkeypatch, tmp_path
):
    note_id = "65abcdef0123456789abcded"
    monkeypatch.setattr(
        xhs_adapter,
        "fetch_text",
        lambda _url, **_kwargs: (_ for _ in ()).throw(
            OMRError("SSR 空壳", exit_code=4)
        ),
    )
    monkeypatch.setattr(
        xhs_adapter.browser_session,
        "render_state",
        lambda *_args, **_kwargs: {
            "__accessRestriction": "扫码登录",
            note_id: {
                "type": "normal",
                "title": "不应采用",
                "imageUrls": ["https://cdn/image.webp"],
            },
        },
    )

    with pytest.raises(OMRError, match="扫码登录"):
        xhs_adapter.fetch(
            f"https://www.xiaohongshu.com/explore/{note_id}", tmp_path
        )


def test_probe_only_browser_fallback_uses_remaining_30_second_budget(
    monkeypatch, tmp_path
):
    note_id = "65abcdef0123456789abcdec"

    class Budget:
        elapsed_ms = 10000

        def __init__(self):
            self.remaining_values = iter([30, 20])

        def remaining(self):
            return next(self.remaining_values)

    monkeypatch.setattr(
        xhs_adapter, "SubtitleProbeBudget", Budget, raising=False
    )
    monkeypatch.setattr(
        xhs_adapter,
        "fetch_text",
        lambda _url, timeout: (_ for _ in ()).throw(
            OMRError("SSR 空壳", exit_code=4)
        ),
    )
    used = {}

    def render(_url, _expr, timeout_ms):
        used["timeout_ms"] = timeout_ms
        return {
            note_id: {
                "type": "video",
                "title": "探测视频",
                "nickname": "作者",
                "imageUrls": [],
            }
        }

    monkeypatch.setattr(xhs_adapter.browser_session, "render_state", render)

    manifest = xhs_adapter.fetch(
        f"https://www.xiaohongshu.com/explore/{note_id}",
        tmp_path,
        probe_only=True,
    )

    assert used["timeout_ms"] == 20000
    assert manifest.content_type == "video"
    assert manifest.subtitle_probe.status == "absent"


def test_image_download_failure_is_reported_without_traceback(tmp_path):
    data = gallery_fixture(tmp_path)
    data["image_items"][0]["url"] = (tmp_path / "missing.webp").as_uri()
    fixture = tmp_path / "missing-image.json"
    fixture.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"

    result = run_entry(
        "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
        out,
        tmp_path,
        fixture=str(fixture),
    )

    assert result.returncode == 4
    assert "图片下载失败" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_ocr_runner_uses_run_workdir_and_local_model_cache(tmp_path):
    image = tmp_path / "source.webp"
    image.write_bytes(b"fake image")
    fake_modules = tmp_path / "fake-modules"
    fake_modules.mkdir()
    (fake_modules / "paddleocr.py").write_text(
        textwrap.dedent(
            """
            import os
            from pathlib import Path

            class PaddleOCR:
                def __init__(self, **kwargs):
                    root = Path(os.environ["OMR_EXPECTED_ROOT"])
                    assert Path(os.environ["PADDLE_PDX_CACHE_HOME"]) == root / ".media" / "tools" / "paddleocr"

                def predict(self, path):
                    assert path.endswith(".jpg")
                    root = Path(os.environ["OMR_EXPECTED_ROOT"])
                    converted = Path(path)
                    assert root / ".media" in converted.parents
                    assert "work" in converted.parts
                    return [{"rec_texts": ["识别文本"]}]
            """
        ),
        encoding="utf-8",
    )
    fake_pil = fake_modules / "PIL"
    fake_pil.mkdir()
    (fake_pil / "__init__.py").write_text("from . import Image\n", encoding="utf-8")
    (fake_pil / "Image.py").write_text(
        textwrap.dedent(
            """
            class FakeImage:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def convert(self, mode):
                    return self

                def save(self, path, format):
                    path.write_bytes(b"converted image")

            def open(path):
                return FakeImage()
            """
        ),
        encoding="utf-8",
    )
    temp_root = tmp_path / "system-temp"
    temp_root.mkdir()
    runner = tmp_path / "run-ocr"
    ocr_runner = SCRIPTS / "omr" / "ocr_runner.py"
    runner.write_text(
        f"#!{sys.executable}\n"
        "import runpy, sys\n"
        f"runner = {str(ocr_runner)!r}\n"
        "sys.argv = [runner, *sys.argv[1:]]\n"
        "runpy.run_path(runner, run_name='__main__')\n",
        encoding="utf-8",
    )
    runner.chmod(runner.stat().st_mode | stat.S_IEXEC)
    data = gallery_fixture(tmp_path)
    data["image_items"] = [{"index": 1, "url": image.as_uri()}]
    fixture = tmp_path / "ocr-cleanup.json"
    fixture.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "ocr.md"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(fake_modules)
    env["TMPDIR"] = str(temp_root)
    env["OMR_FIXTURE"] = str(fixture)
    env["OMR_OCR_BIN"] = str(runner)
    env["OMR_EXPECTED_ROOT"] = str(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(ENTRY),
            "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "识别文本" in out.read_text(encoding="utf-8")
    assert list(temp_root.iterdir()) == []
