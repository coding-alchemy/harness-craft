#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""online-media-reader 唯一执行入口。

用法：
    python3 scripts/read.py URL [--output PATH.md] [--keep-media] [--verify-audio]
                            [--whisper-model MODEL]
    python3 scripts/read.py URL --probe-only
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omr import adapters  # noqa: E402  确保适配器注册
from omr.adapters import fetch_manifest  # noqa: E402
from omr.model import OMRError  # noqa: E402
from omr.pipeline import process  # noqa: E402
from omr.render import render_markdown  # noqa: E402
from omr.router import detect_platform  # noqa: E402
from omr.subtitles import finalize_probe  # noqa: E402
from omr.workspace import RunWorkspace  # noqa: E402


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise OMRError(f"参数错误：{message}", exit_code=2)


def parse_args(argv):
    parser = StructuredArgumentParser(
        prog="online-media-reader", description="从公开链接读取媒体文字并输出 Markdown"
    )
    parser.add_argument("url", help="受支持平台的公开单条内容 URL")
    parser.add_argument("--output", "-o", help="Markdown 输出路径")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="只探测在线字幕并输出 JSON，不下载媒体或执行 ASR",
    )
    parser.add_argument(
        "--keep-media", action="store_true", help="保留下载的媒体文件（永不保留 Cookie）"
    )
    parser.add_argument(
        "--verify-audio", action="store_true", help="即使字幕可靠也下载原音并执行 ASR 核验"
    )
    parser.add_argument(
        "--whisper-model", default="small", help="faster-whisper 模型，默认 small"
    )
    return parser.parse_args(argv)


def _run_probe(args, platform):
    media_root = Path.cwd() / ".media"
    media_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=".probe-", dir=media_root))
    try:
        manifest = fetch_manifest(platform, args.url, workdir, probe_only=True)
        probe = finalize_probe(manifest)
        decision = (
            "use_ocr"
            if manifest.content_type != "video"
            else "use_subtitle" if probe.status == "usable" else "use_asr"
        )
        print(
            json.dumps(
                {
                    "decision": decision,
                    "status": probe.status,
                    "reason": probe.reason,
                    "elapsed_ms": probe.elapsed_ms,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        for cookie in workdir.rglob("cookies.txt"):
            try:
                cookie.unlink(missing_ok=True)
            except OSError:
                pass
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            media_root.rmdir()
        except OSError:
            pass


def _print_failure(exc, stage, workspace=None, manifest=None):
    error = str(exc)
    if workspace is None:
        payload = {
            "status": "error",
            "stage": stage,
            "error": error,
            "run_dir": None,
        }
    elif workspace.status == "error" and workspace.error is not None:
        payload = workspace.failure_payload()
    else:
        workspace.stage = stage
        try:
            workspace.fail(error, manifest)
            payload = workspace.failure_payload()
        except OSError as state_error:
            payload = {
                "status": "error",
                "stage": stage,
                "error": f"{error}；运行清单写入失败：{state_error}",
                "run_dir": str(workspace.run_dir),
            }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def main(argv=None):
    stage = "routing"
    workspace = None
    manifest = None
    try:
        args = parse_args(argv)
        platform = detect_platform(args.url)
        if args.probe_only:
            stage = "probing"
            return _run_probe(args, platform)

        workspace = RunWorkspace.create(
            Path.cwd(), platform, args.url, output=args.output
        )
        stage = "fetching"
        workspace.set_stage(stage)
        manifest = fetch_manifest(
            platform, args.url, workspace.work_dir, probe_only=False
        )
        workspace.bind_manifest(manifest)
        finalize_probe(manifest)
        stage = "processing"
        workspace.set_stage(stage, manifest)
        process(
            manifest,
            workspace.work_dir,
            workspace.artifacts_dir,
            keep_media=args.keep_media,
            verify_audio=args.verify_audio,
            whisper_model=args.whisper_model,
        )
        stage = "rendering"
        workspace.set_stage(stage, manifest)
        markdown = render_markdown(manifest)
        stage = "delivering"
        workspace.set_stage(stage, manifest)
        workspace.deliver(markdown)
        workspace.complete(manifest)
        print(json.dumps(workspace.success_payload(), ensure_ascii=False))
        return 0
    except OMRError as exc:
        _print_failure(exc, stage, workspace, manifest)
        return exc.exit_code
    except KeyboardInterrupt:
        _print_failure("用户中断", stage, workspace, manifest)
        return 130
    except Exception as exc:
        _print_failure(f"{type(exc).__name__}: {exc}", stage, workspace, manifest)
        return 1
    finally:
        if workspace is not None:
            try:
                workspace.cleanup_cookies(manifest)
            except OSError:
                # fail()/complete() 已负责把清理错误纳入主结果；此处只做最终兜底，
                # 不得用二次清理失败覆盖原始异常或用户中断。
                pass


if __name__ == "__main__":
    sys.exit(main())
