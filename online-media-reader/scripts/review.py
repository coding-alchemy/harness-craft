#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ASR 画面复核入口：校验结构化纠正并原子重渲染唯一正文。

用法：
    python3 scripts/review.py <run_dir> --corrections <corrections.json>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omr import review  # noqa: E402
from omr.model import OMRError  # noqa: E402
from omr.workspace import RunWorkspace  # noqa: E402


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise OMRError(f"参数错误：{message}", exit_code=2)


def parse_args(argv):
    parser = StructuredArgumentParser(
        prog="online-media-reader-review",
        description="校验 ASR 画面复核纠正并原子更新唯一正文",
    )
    parser.add_argument("run_dir", help="主读取入口返回的运行目录")
    parser.add_argument(
        "--corrections", required=True, help="结构化纠正 JSON 文件路径"
    )
    return parser.parse_args(argv)


def _print_failure(exc, stage, run_dir=None, workspace=None):
    error = str(exc)
    payload = None
    if workspace is not None:
        run_dir = str(workspace.run_dir)
        if workspace.status == "error":
            stage = workspace.stage or stage
            error = workspace.error or error
        try:
            payload = workspace.record_review_failure(error, stage)
        except OSError as state_error:
            state_detail = f"运行清单写入失败：{state_error}"
            if state_detail not in error:
                error = f"{error}；{state_detail}"
    if payload is None:
        payload = {
            "status": "error",
            "stage": stage,
            "error": error,
            "run_dir": run_dir,
        }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def main(argv=None):
    run_dir_arg = None
    workspace = None
    stage = "loading"
    try:
        args = parse_args(argv)
        run_dir_arg = str(Path(args.run_dir).resolve())
        workspace = RunWorkspace.load(args.run_dir)
        stage = "reviewing"
        workspace.start_review_attempt()
        payload = review.apply(workspace, args.corrections)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except OMRError as exc:
        _print_failure(exc, stage, run_dir_arg, workspace)
        return exc.exit_code
    except KeyboardInterrupt:
        _print_failure("用户中断", stage, run_dir_arg, workspace)
        return 130
    except Exception as exc:
        _print_failure(f"{type(exc).__name__}: {exc}", stage, run_dir_arg, workspace)
        return 1


if __name__ == "__main__":
    sys.exit(main())
