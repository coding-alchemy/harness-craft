import argparse
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .client import ConnectorError, FeishuClient, LOGGER
from .config import (
    ConfigError,
    build_config_paths,
    config_from_settings,
    format_source_diagnostics,
    missing_required_fields,
    resolve_settings,
)


EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_REMOTE = 4
EXIT_TRANSIENT = 5


def redact_identifier(value):
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return "***"
    prefix = "ou_" if value.startswith("ou_") else value[:2]
    return "%s…%s" % (prefix, value[-4:])


def non_empty(value):
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise argparse.ArgumentTypeError(
            "value must contain valid Unicode scalar text"
        ) from exc
    if not value.strip():
        raise argparse.ArgumentTypeError("value must not be empty")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description="Send plain-text Feishu messages")
    parser.add_argument(
        "--project-root",
        type=Path,
        help="override project root used for .config/feishu-connector/config.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send", help="send explicit plain text")
    send_parser.add_argument("--message", required=True, type=non_empty)

    task_parser = subparsers.add_parser("task", help="send a task notification")
    task_parser.add_argument("--status", required=True, choices=("success", "failure"))
    task_parser.add_argument("--task", required=True, type=non_empty)
    task_parser.add_argument("--summary", required=True, type=non_empty)
    task_parser.add_argument("--repo", required=True, type=non_empty)
    task_parser.add_argument("--branch", required=True, type=non_empty)
    task_parser.add_argument("--source", choices=("Codex", "OpenCode"), default="Codex")
    task_parser.add_argument(
        "--auto",
        action="store_true",
        help="send only when merged notification.autoNotify=true",
    )
    subparsers.add_parser(
        "config", help="show effective configuration sources without network access"
    )
    subparsers.add_parser("stdin", help="read a safe notification request from stdin")
    return parser


def render_task_message(source, status, task, summary, repo, branch):
    fields = {
        "source": source,
        "status": status,
        "task": task,
        "summary": summary,
        "repo": repo,
        "branch": branch,
    }
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s must not be empty" % name)
    return (
        "[%s] %s\n"
        "任务：%s\n"
        "摘要：%s\n"
        "仓库：%s\n"
        "分支：%s"
        % (source, status.upper(), task, summary, repo, branch)
    )


def _connector_exit_code(error):
    if error.retryable or error.category in ("network", "rate_limit", "server"):
        return EXIT_TRANSIENT
    return EXIT_REMOTE


def _stdin_argv(payload):
    if not isinstance(payload, dict):
        return None
    if set(payload) == {"flow", "message"} and payload.get("flow") == "send":
        message = payload.get("message")
        if isinstance(message, str) and "\x00" not in message:
            return ["send", "--message", message]
        return None
    task_keys = {"flow", "status", "task", "summary", "repo", "branch"}
    if set(payload) != task_keys or payload.get("flow") != "task-auto":
        return None
    fields = ("status", "task", "summary", "repo", "branch")
    if not all(isinstance(payload.get(field), str) for field in fields):
        return None
    return [
        "task",
        "--auto",
        "--status", payload["status"],
        "--task", payload["task"],
        "--summary", payload["summary"],
        "--repo", payload["repo"],
        "--branch", payload["branch"],
    ]


def _run_main(
    args,
    environ=None,
    config_paths=None,
    client_factory=FeishuClient,
    stdout=None,
    stderr=None,
    cwd=None,
    home=None,
    git_runner=subprocess.run,
):
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    paths = config_paths
    try:
        if paths is None:
            paths = build_config_paths(
                explicit_project_root=args.project_root,
                cwd=Path.cwd() if cwd is None else cwd,
                home=Path.home() if home is None else home,
                git_runner=git_runner,
            )

        settings = resolve_settings(paths, environ)
        if args.command == "config":
            resolution = config_from_settings(settings)
            print(format_source_diagnostics(resolution), file=stdout)
            return EXIT_OK

        if args.command == "task" and args.auto:
            if not settings.values["notification.autoNotify"]:
                print("Feishu auto notification disabled; nothing sent", file=stdout)
                return EXIT_OK

        config = config_from_settings(settings).config
        if args.command == "send":
            message = args.message
        else:
            message = render_task_message(
                args.source,
                args.status,
                args.task,
                args.summary,
                args.repo,
                args.branch,
            )
        client_factory(config).send_text(message)
        print(
            "Feishu message sent to %s" % redact_identifier(config.receive_open_id),
            file=stdout,
        )
        return EXIT_OK
    except ConfigError as exc:
        print("Feishu configuration error: %s" % exc, file=stderr)
        return EXIT_CONFIG
    except ConnectorError as exc:
        code_text = " code=%s" % exc.code if exc.code is not None else ""
        print(
            "Feishu notification warning [%s]%s: %s"
            % (exc.category, code_text, exc),
            file=stderr,
        )
        return _connector_exit_code(exc)


def main(
    argv=None,
    environ=None,
    config_paths=None,
    client_factory=FeishuClient,
    stdin=None,
    stdout=None,
    stderr=None,
    cwd=None,
    home=None,
    git_runner=subprocess.run,
):
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    handler = logging.StreamHandler(stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    previous_level = LOGGER.level
    previous_propagate = LOGGER.propagate
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.WARNING)
    LOGGER.propagate = False
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.command == "stdin":
            project_root = args.project_root
            try:
                stdin_argv = _stdin_argv(json.load(stdin))
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                stdin_argv = None
            if stdin_argv is None:
                print("Invalid stdin input", file=stderr)
                return 2
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    args = parser.parse_args(stdin_argv)
            except SystemExit:
                print("Invalid stdin input", file=stderr)
                return 2
            args.project_root = project_root
        return _run_main(
            args,
            environ=environ,
            config_paths=config_paths,
            client_factory=client_factory,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            home=home,
            git_runner=git_runner,
        )
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(previous_level)
        LOGGER.propagate = previous_propagate
        handler.close()
