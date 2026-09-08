#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匿名浏览器子进程；父进程负责 cookies/state 两种任务的硬墙钟。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omr.browser_session import _collect_cookies, _collect_state  # noqa: E402
from omr.model import OMRError  # noqa: E402


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    try:
        mode, url, timeout_ms = args
        if mode == "cookies":
            payload = {"cookies": _collect_cookies(url, int(timeout_ms))}
        elif mode == "state":
            payload = {
                "state": _collect_state(
                    url, sys.stdin.read(), int(timeout_ms)
                )
            }
        else:
            raise ValueError(f"未知浏览器任务：{mode}")
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except OMRError as exc:
        print(
            json.dumps(
                {"error": str(exc), "exit_code": exc.exit_code},
                ensure_ascii=False,
            )
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {"error": f"匿名浏览器访问失败：{exc}", "exit_code": 4},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
