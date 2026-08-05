#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


INVALID_INPUT_EXIT = 2
CLI_PATH = Path(__file__).with_name("feishu_notify.py")


def _argv_for(payload):
    if not isinstance(payload, dict):
        return None
    flow = payload.get("flow")
    if flow == "send" and set(payload) == {"flow", "message"}:
        message = payload["message"]
        if isinstance(message, str) and message.strip() and "\u0000" not in message:
            return [
                sys.executable,
                str(CLI_PATH),
                "send",
                "--message=%s" % message,
            ]
    if flow == "task-auto" and set(payload) == {
        "flow",
        "status",
        "task",
        "summary",
        "repo",
        "branch",
    }:
        fields = ("status", "task", "summary", "repo", "branch")
        if (
            payload["status"] in ("success", "failure")
            and all(isinstance(payload[field], str) for field in fields)
            and all(payload[field].strip() for field in fields)
            and all("\u0000" not in payload[field] for field in fields)
        ):
            return [
                sys.executable,
                str(CLI_PATH),
                "task",
                "--auto",
                "--status=%s" % payload["status"],
                "--task=%s" % payload["task"],
                "--summary=%s" % payload["summary"],
                "--repo=%s" % payload["repo"],
                "--branch=%s" % payload["branch"],
            ]
    return None


def main(stdin=None, stderr=None):
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    try:
        payload = json.loads(stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        payload = None
    argv = _argv_for(payload)
    if argv is None:
        print("Invalid adapter input", file=stderr)
        return INVALID_INPUT_EXIT
    try:
        return subprocess.run(argv, check=False, shell=False).returncode
    except (OSError, ValueError, UnicodeError) as exc:
        print("Invalid adapter input: subprocess error — %s" % exc, file=stderr)
        return INVALID_INPUT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
