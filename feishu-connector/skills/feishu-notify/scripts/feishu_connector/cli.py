import argparse
import contextlib
import io
import json
import logging
import os
import shlex
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
    resolve_project_root,
    resolve_settings,
)


class PrepareError(Exception):
    pass


EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_REMOTE = 4
EXIT_TRANSIENT = 5

TASK_STATUS = {
    "success": ("任务完成", "green"),
    "failure": ("任务失败", "red"),
    "confirm": ("待确认", "orange"),
}

LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")

VALUE_OPTIONS = frozenset(
    {
        "--message",
        "--title",
        "--status",
        "--project",
        "--conversation",
        "--content",
    }
)

MAX_PREPARED_COMMAND_BYTES = 96 * 1024


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


def _validate_task_text(name, value, single_line=False):
    if not isinstance(value, str):
        raise ValueError("%s must be text" % name)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "%s must contain valid Unicode scalar text" % name
        ) from exc
    if not value.strip() or "\x00" in value:
        raise ValueError("%s must not be empty or contain NUL" % name)
    if single_line and any(char in LINE_BREAKS for char in value):
        raise ValueError("%s must be a single line" % name)
    return value


def _task_argument(name, value, single_line=False):
    try:
        return _validate_task_text(name, value, single_line=single_line)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def single_line_non_empty(value):
    return _task_argument("value", value, single_line=True)


def task_content(value):
    return _task_argument("content", value)


def _stdin_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate stdin JSON key")
        result[key] = value
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send plain-text, rich-text, and task-card Feishu messages"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="override project root used for .config/feishu-connector/config.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send", help="send explicit plain text")
    send_parser.add_argument("--message", required=True, type=non_empty)

    task_parser = subparsers.add_parser("task", help="send a task notification")
    task_parser.add_argument(
        "--status", required=True, choices=tuple(TASK_STATUS)
    )
    task_parser.add_argument(
        "--project", required=True, type=single_line_non_empty
    )
    task_parser.add_argument(
        "--conversation", required=True, type=single_line_non_empty
    )
    task_parser.add_argument("--content", required=True, type=task_content)
    task_parser.add_argument(
        "--auto",
        action="store_true",
        help="send only when merged notification.autoNotify=true",
    )
    rich_parser = subparsers.add_parser("rich", help="send an explicit rich message")
    rich_parser.add_argument(
        "--title", required=True, type=lambda value: _task_argument(
            "title", value, single_line=True
        )
    )
    rich_parser.add_argument("--content", required=True, type=task_content)
    subparsers.add_parser(
        "config", help="show effective configuration sources without network access"
    )
    subparsers.add_parser("stdin", help="read a safe notification request from stdin")
    subparsers.add_parser(
        "prepare-shell",
        help="prepare an approval-visible POSIX shell send command",
    )
    return parser


def render_task_card(status, project, conversation, content):
    try:
        label, color = TASK_STATUS[status]
    except (KeyError, TypeError) as exc:
        raise ValueError("status must be success, failure, or confirm") from exc
    project = _validate_task_text("project", project, single_line=True)
    conversation = _validate_task_text(
        "conversation", conversation, single_line=True
    )
    content = _validate_task_text("content", content)
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {
                "tag": "plain_text",
                "content": "%s-%s-%s" % (project, conversation, label),
            },
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}}
        ],
    }


def render_rich_card(title, content):
    title = _validate_task_text("title", title, single_line=True)
    content = _validate_task_text("content", content)
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}}
        ],
    }


def _connector_exit_code(error):
    if (
        error.retryable
        or error.category == "network"
        or error.category.startswith("network.")
        or error.category in ("rate_limit", "server")
    ):
        return EXIT_TRANSIENT
    return EXIT_REMOTE


def _stdin_argv(payload):
    if not isinstance(payload, dict):
        return None
    flows = {
        "send": ("message",),
        "rich": ("title", "content"),
        "task": ("status", "project", "conversation", "content"),
        "task-auto": ("status", "project", "conversation", "content"),
    }
    flow = payload.get("flow")
    fields = flows.get(flow)
    if fields is None or set(payload) != {"flow", *fields}:
        return None
    if not all(
        isinstance(payload[field], str) and "\x00" not in payload[field]
        for field in fields
    ):
        return None
    if flow == "send":
        return ["send", "--message", payload["message"]]
    if flow == "rich":
        return ["rich", "--title", payload["title"], "--content", payload["content"]]
    argv = ["task"]
    if flow == "task-auto":
        argv.append("--auto")
    return argv + [
        "--status", payload["status"],
        "--project", payload["project"],
        "--conversation", payload["conversation"],
        "--content", payload["content"],
    ]


def _read_stdin_args(stdin, parser, shell=False):
    try:
        request_argv = _stdin_argv(
            json.load(stdin, object_pairs_hook=_stdin_json_object)
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError, RecursionError):
        return None
    if request_argv is None:
        return None
    parse_argv = _shell_send_argv(request_argv) if shell else request_argv
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            request_args = parser.parse_args(parse_argv)
    except SystemExit:
        return None
    return request_args, request_argv


def _resolved_file(value):
    try:
        path = Path(value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PrepareError("Unable to prepare shell command") from exc
    if not path.is_file():
        raise PrepareError("Unable to prepare shell command")
    return path


def _shell_send_argv(argv):
    normalized = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in VALUE_OPTIONS:
            normalized.append("%s=%s" % (item, argv[index + 1]))
            index += 2
        else:
            normalized.append(item)
            index += 1
    return normalized


def _prepare_shell_command(
    request_argv,
    explicit_project_root,
    cwd,
    git_runner,
):
    if os.name != "posix":
        raise PrepareError("POSIX shell is required")
    interpreter = _resolved_file(sys.executable)
    launcher = _resolved_file(sys.argv[0])
    try:
        project_root = resolve_project_root(
            explicit_project_root,
            cwd,
            git_runner=git_runner,
        )
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
        raise PrepareError("Unable to prepare shell command") from exc
    command = shlex.join(
        [
            str(interpreter),
            str(launcher),
            "--project-root=%s" % project_root,
            *_shell_send_argv(request_argv),
        ]
    )
    try:
        command_bytes = command.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PrepareError("Unable to prepare shell command") from exc
    if len(command_bytes) > MAX_PREPARED_COMMAND_BYTES:
        raise PrepareError("Prepared command exceeds 96 KiB limit")
    return command


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
                print("Feishu notification skipped: autoNotify=false", file=stdout)
                return EXIT_OK

        config = config_from_settings(settings).config
        if args.command == "send":
            client_factory(config).send_text(args.message)
        elif args.command == "rich":
            client_factory(config).send_card(
                render_rich_card(args.title, args.content)
            )
        elif args.command == "task":
            card = render_task_card(
                args.status,
                args.project,
                args.conversation,
                args.content,
            )
            client_factory(config).send_card(card)
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
    stdout = sys.stdout if stdout is None else stdout
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
        if args.command in ("stdin", "prepare-shell"):
            source_command = args.command
            explicit_project_root = args.project_root
            parsed = _read_stdin_args(
                stdin, parser, shell=source_command == "prepare-shell"
            )
            if parsed is None:
                print("Invalid stdin input", file=stderr)
                return 2
            args, request_argv = parsed
            args.project_root = explicit_project_root
            if source_command == "prepare-shell":
                try:
                    command = _prepare_shell_command(
                        request_argv,
                        explicit_project_root,
                        Path.cwd() if cwd is None else cwd,
                        git_runner,
                    )
                except PrepareError as exc:
                    print(str(exc), file=stderr)
                    return 2
                print(command, file=stdout)
                return EXIT_OK
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
