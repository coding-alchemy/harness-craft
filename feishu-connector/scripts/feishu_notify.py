#!/usr/bin/env python3
import argparse
import http.client
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


CONFIG_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_RECEIVE_OPEN_ID",
    "FEISHU_AUTO_NOTIFY",
)

EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_REMOTE = 4
EXIT_TRANSIENT = 5

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    app_id: str
    app_secret: str
    receive_open_id: str
    auto_notify: bool


def parse_bool(value, key):
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigError("%s must be true or false" % key)


def load_env_file(path):
    path = Path(path)
    try:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError("unable to read .env configuration") from exc
    values = {}
    for line_number, raw_line in enumerate(
        text.splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigError("invalid .env assignment at line %d" % line_number)
        values[key] = value.strip()
    return values


def merged_settings(path, environ):
    values = load_env_file(path)
    for key in CONFIG_KEYS:
        if key in environ:
            values[key] = environ[key]
    return values


def auto_notify_enabled(path, environ):
    values = merged_settings(path, environ)
    return parse_bool(
        values.get("FEISHU_AUTO_NOTIFY", "false"),
        "FEISHU_AUTO_NOTIFY",
    )


def load_config(path, environ):
    values = merged_settings(path, environ)
    required = (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_RECEIVE_OPEN_ID",
    )
    for key in required:
        if not values.get(key, "").strip():
            raise ConfigError("missing required configuration: %s" % key)
    return Config(
        app_id=values["FEISHU_APP_ID"].strip(),
        app_secret=values["FEISHU_APP_SECRET"].strip(),
        receive_open_id=values["FEISHU_RECEIVE_OPEN_ID"].strip(),
        auto_notify=parse_bool(
            values.get("FEISHU_AUTO_NOTIFY", "false"),
            "FEISHU_AUTO_NOTIFY",
        ),
    )


def redact_identifier(value):
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return "***"
    prefix = "ou_" if value.startswith("ou_") else value[:2]
    return "%s…%s" % (prefix, value[-4:])


@dataclass(frozen=True)
class JsonResponse:
    status: int
    payload: Mapping[str, object]


class NetworkFailure(Exception):
    pass


class ConnectorError(Exception):
    def __init__(self, category, message, retryable=False, code=None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.code = code


def _decode_response(raw):
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectorError("protocol", "Feishu returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ConnectorError("protocol", "Feishu returned a non-object JSON response")
    return decoded


def post_json(url, headers, payload, timeout):
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return JsonResponse(response.status, _decode_response(response.read()))
    except urllib.error.HTTPError as exc:
        try:
            response_payload = _decode_response(exc.read())
        except (ConnectorError, http.client.HTTPException, OSError):
            return JsonResponse(exc.code, {})
        return JsonResponse(exc.code, response_payload)
    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise NetworkFailure("Feishu request failed") from exc


class FeishuClient:
    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MESSAGE_URL = (
        "https://open.feishu.cn/open-apis/im/v1/messages"
        "?receive_id_type=open_id"
    )
    RATE_LIMIT_CODES = {230020}

    def __init__(
        self,
        config,
        transport=post_json,
        sleep=time.sleep,
        timeout=10.0,
        max_retries=2,
    ):
        self.config = config
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout
        self.max_retries = max_retries

    def _classify_response(self, response):
        code = response.payload.get("code")
        try:
            numeric_code = int(code) if code is not None else None
        except (TypeError, ValueError):
            numeric_code = None
        if response.status == 429 or numeric_code in self.RATE_LIMIT_CODES:
            raise ConnectorError(
                "rate_limit",
                "Feishu rate limit",
                retryable=True,
                code=numeric_code,
            )
        if response.status >= 500:
            raise ConnectorError(
                "server",
                "Feishu server error (HTTP %d)" % response.status,
                retryable=True,
                code=numeric_code,
            )
        if not 200 <= response.status < 300:
            raise ConnectorError(
                "api",
                "Feishu request rejected (HTTP %d)" % response.status,
                code=numeric_code,
            )
        if numeric_code != 0:
            raise ConnectorError(
                "api",
                "Feishu business error",
                code=numeric_code,
            )
        return response.payload

    def _attempt(self, operation):
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except NetworkFailure as exc:
                error = ConnectorError(
                    "network",
                    "Feishu network request failed",
                    retryable=True,
                )
                error.__cause__ = exc
            except ConnectorError as exc:
                error = exc
            if not error.retryable:
                raise error
            if attempt == self.max_retries:
                raise ConnectorError(
                    error.category,
                    "%s after %d attempts" % (str(error), attempt + 1),
                    retryable=True,
                    code=error.code,
                ) from error
            LOGGER.warning(
                "Feishu retry [%s] attempt %d/%d",
                error.category,
                attempt + 1,
                self.max_retries + 1,
            )
            self.sleep(min(2.0 ** attempt, 4.0))
        raise AssertionError("unreachable")

    def _post(self, url, headers, payload):
        response = self.transport(url, headers, payload, self.timeout)
        return self._classify_response(response)

    def fetch_tenant_access_token(self):
        payload = self._attempt(
            lambda: self._post(
                self.TOKEN_URL,
                {},
                {
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise ConnectorError(
                "auth",
                "Feishu authentication response missing tenant_access_token",
            )
        return token

    def send_text(self, message):
        token = self.fetch_tenant_access_token()
        content = json.dumps(
            {"text": message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return self._attempt(
            lambda: self._post(
                self.MESSAGE_URL,
                {"Authorization": "Bearer %s" % token},
                {
                    "receive_id": self.config.receive_open_id,
                    "msg_type": "text",
                    "content": content,
                },
            )
        )


def non_empty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("value must not be empty")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description="Send plain-text Feishu messages")
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
        help="send only when FEISHU_AUTO_NOTIFY=true",
    )
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


def default_env_file():
    return Path(__file__).resolve().parents[1] / ".env"


def _connector_exit_code(error):
    if error.retryable or error.category in ("network", "rate_limit", "server"):
        return EXIT_TRANSIENT
    return EXIT_REMOTE


def main(
    argv=None,
    environ=None,
    env_file=None,
    client_factory=FeishuClient,
    stdout=None,
    stderr=None,
):
    environ = os.environ if environ is None else environ
    env_file = default_env_file() if env_file is None else Path(env_file)
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)

    try:
        if args.command == "task" and args.auto:
            if not auto_notify_enabled(env_file, environ):
                print("Feishu auto notification disabled; nothing sent", file=stdout)
                return EXIT_OK

        config = load_config(env_file, environ)
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


if __name__ == "__main__":
    raise SystemExit(main())
