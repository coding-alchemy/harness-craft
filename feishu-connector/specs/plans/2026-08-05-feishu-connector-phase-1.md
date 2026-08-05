# Feishu Connector Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python-standard-library CLI and thin Codex Skill that send plain-text direct messages from a Feishu custom app bot to one fixed Open ID, with optional task-completion notifications that never change the originating task result.

**Architecture:** Keep all Feishu configuration, authentication, HTTP, retry, rendering, and exit-code behavior in `feishu-connector/scripts/feishu_notify.py`. The Codex Skill is a policy adapter that invokes the CLI for explicit sends and task-completion sends; it never implements Feishu API logic or reads secrets itself. Unit tests import the script as a module and inject fake transports, clocks, streams, and environments so the default suite remains offline.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `pathlib`, `time`, `typing`, `urllib`, `unittest`, `unittest.mock`), Markdown, Git.

## Global Constraints

- Implement only Phase 1 from `feishu-connector/specs/feishu-connector.md`; do not implement Phase 2 JSON configuration.
- Support plain-text direct messages to exactly one configured Open ID.
- Use a Feishu custom app bot and application-identity access token; do not use a group custom-bot Webhook.
- Use Python 3 standard library only; do not add package managers, virtual environments, or third-party dependencies.
- Read Phase 1 settings from `feishu-connector/.env`, with process environment variables overriding matching keys.
- Never accept App Secret on the command line or print App Secret, access token, or the complete Open ID.
- Retry transient network, rate-limit, and HTTP 5xx errors at most two additional times; do not retry validation, authentication, permission, or recipient errors.
- A notification failure must never replace or alter the originating Codex/OpenCode task status.
- All default tests must run without network access or real Feishu credentials.
- Before implementing the Skill task, invoke `skill-creator` and `superpowers:writing-skills` and follow their current instructions.
- Make one focused commit at the end of each task.

## File Map

| Path | Responsibility |
|---|---|
| `feishu-connector/scripts/feishu_notify.py` | Config parsing, redaction, HTTP transport, Feishu client, retry policy, message rendering, CLI parsing, and exit codes |
| `feishu-connector/tests/test_config.py` | `.env`, process override, Boolean parsing, missing configuration, and redaction tests |
| `feishu-connector/tests/test_client.py` | Token and message payloads, JSON encoding, error classification, and retry tests |
| `feishu-connector/tests/test_cli.py` | CLI parsing, task template, auto-notify gate, output, and exit-code tests |
| `feishu-connector/tests/test_skill_contract.py` | Static contract checks for explicit and automatic Skill workflows |
| `feishu-connector/skills/feishu-notify/SKILL.md` | Thin Codex adapter and notification policy |
| `feishu-connector/.env.example` | Credential-free Phase 1 configuration template |
| `.gitignore` | Excludes the real `feishu-connector/.env` and macOS metadata |
| `feishu-connector/README.md` | Feishu setup, local configuration, CLI, Skill setup, testing, troubleshooting, and manual acceptance |

---

### Task 1: Configuration, redaction, and repository safety

**Files:**
- Create: `feishu-connector/scripts/feishu_notify.py`
- Create: `feishu-connector/tests/test_config.py`
- Create: `feishu-connector/.env.example`
- Create: `.gitignore`

**Interfaces:**
- Produces: `Config`, `ConfigError`, `load_env_file(path)`, `merged_settings(path, environ)`, `load_config(path, environ)`, `auto_notify_enabled(path, environ)`, `parse_bool(value, key)`, and `redact_identifier(value)`.
- `Config` fields: `app_id: str`, `app_secret: str`, `receive_open_id: str`, `auto_notify: bool`.
- Later tasks must use these functions instead of rereading `.env` or environment variables.

- [ ] **Step 1: Write failing configuration tests**

Create `feishu-connector/tests/test_config.py`:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from feishu_notify import (  # noqa: E402
    ConfigError,
    auto_notify_enabled,
    load_config,
    load_env_file,
    parse_bool,
    redact_identifier,
)


class ConfigTests(unittest.TestCase):
    def write_env(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_comments_blank_lines_and_equals_in_value(self):
        path = self.write_env(
            "# local only\n"
            "\n"
            "FEISHU_APP_ID=cli_local\n"
            "FEISHU_APP_SECRET=abc=def\n"
            "FEISHU_RECEIVE_OPEN_ID=ou_local\n"
            "FEISHU_AUTO_NOTIFY=false\n"
        )
        values = load_env_file(path)
        self.assertEqual("abc=def", values["FEISHU_APP_SECRET"])

    def test_process_environment_overrides_file_by_field(self):
        path = self.write_env(
            "FEISHU_APP_ID=cli_file\n"
            "FEISHU_APP_SECRET=file-secret\n"
            "FEISHU_RECEIVE_OPEN_ID=ou_file\n"
            "FEISHU_AUTO_NOTIFY=false\n"
        )
        config = load_config(
            path,
            {
                "FEISHU_APP_ID": "cli_env",
                "FEISHU_AUTO_NOTIFY": "true",
            },
        )
        self.assertEqual("cli_env", config.app_id)
        self.assertEqual("file-secret", config.app_secret)
        self.assertEqual("ou_file", config.receive_open_id)
        self.assertTrue(config.auto_notify)

    def test_environment_can_supply_all_values_when_file_is_missing(self):
        config = load_config(
            Path("/path/that/does/not/exist"),
            {
                "FEISHU_APP_ID": "cli_env",
                "FEISHU_APP_SECRET": "env-secret",
                "FEISHU_RECEIVE_OPEN_ID": "ou_env",
                "FEISHU_AUTO_NOTIFY": "false",
            },
        )
        self.assertEqual("cli_env", config.app_id)

    def test_missing_required_key_names_key_without_value(self):
        path = self.write_env("FEISHU_APP_ID=cli_only\n")
        with self.assertRaisesRegex(ConfigError, "FEISHU_APP_SECRET"):
            load_config(path, {})

    def test_invalid_line_fails_before_configuration_is_used(self):
        path = self.write_env("not-an-assignment\n")
        with self.assertRaisesRegex(ConfigError, "line 1"):
            load_env_file(path)

    def test_boolean_parser_is_strict_and_case_insensitive(self):
        self.assertTrue(parse_bool("TRUE", "FEISHU_AUTO_NOTIFY"))
        self.assertFalse(parse_bool("false", "FEISHU_AUTO_NOTIFY"))
        with self.assertRaisesRegex(ConfigError, "true or false"):
            parse_bool("yes", "FEISHU_AUTO_NOTIFY")

    def test_auto_notify_gate_does_not_require_credentials(self):
        path = self.write_env("FEISHU_AUTO_NOTIFY=true\n")
        self.assertTrue(auto_notify_enabled(path, {}))

    def test_redacts_identifier_without_returning_complete_value(self):
        value = "ou_1234567890abcdef"
        redacted = redact_identifier(value)
        self.assertNotEqual(value, redacted)
        self.assertTrue(redacted.startswith("ou_"))
        self.assertTrue(redacted.endswith("cdef"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the configuration tests and confirm the expected failure**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'feishu_notify'`.

- [ ] **Step 3: Implement the minimal configuration and redaction layer**

Create `feishu-connector/scripts/feishu_notify.py` with this initial content:

```python
#!/usr/bin/env python3
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


CONFIG_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_RECEIVE_OPEN_ID",
    "FEISHU_AUTO_NOTIFY",
)


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
    if not path.exists():
        return {}
    values = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
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
```

Do not add HTTP or CLI code in this task.

- [ ] **Step 4: Add the credential-free template and ignore rules**

Create `feishu-connector/.env.example`:

```dotenv
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_RECEIVE_OPEN_ID=
FEISHU_AUTO_NOTIFY=false
```

Create `.gitignore`:

```gitignore
.DS_Store
workflow/.DS_Store
feishu-connector/.env
__pycache__/
*.py[cod]
```

- [ ] **Step 5: Run focused tests and verify the real `.env` is ignored**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
git check-ignore -q --no-index feishu-connector/.env
git diff --check
```

Expected: 8 tests pass, `git check-ignore` exits `0`, and `git diff --check` prints nothing.

- [ ] **Step 6: Commit the configuration boundary**

```bash
git add .gitignore feishu-connector/.env.example feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_config.py
git commit -m "feat: add Feishu connector configuration"
```

---

### Task 2: Feishu HTTP client, authentication, and retry policy

**Files:**
- Modify: `feishu-connector/scripts/feishu_notify.py`
- Create: `feishu-connector/tests/test_client.py`

**Interfaces:**
- Consumes: `Config` from Task 1.
- Produces: `JsonResponse(status, payload)`, `NetworkFailure`, `ConnectorError(category, message, retryable, code)`, `post_json(url, headers, payload, timeout)`, and `FeishuClient.send_text(message)`.
- Injected transport signature: `(url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout: float) -> JsonResponse`.
- Injected sleeper signature: `(delay_seconds: float) -> None`.

- [ ] **Step 1: Write failing client and retry tests**

Create `feishu-connector/tests/test_client.py`:

```python
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from feishu_notify import (  # noqa: E402
    Config,
    ConnectorError,
    FeishuClient,
    JsonResponse,
    NetworkFailure,
)


class FakeTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, dict(headers), dict(payload), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ClientTests(unittest.TestCase):
    def config(self):
        return Config("cli_test", "secret-value", "ou_target1234", False)

    def test_fetches_token_then_sends_double_encoded_plain_text(self):
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(200, {"code": 0, "msg": "success", "data": {}}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
        client.send_text('中文 "quoted"\nnext line')

        token_call, message_call = transport.calls
        self.assertTrue(token_call[0].endswith("/auth/v3/tenant_access_token/internal"))
        self.assertEqual(
            {"app_id": "cli_test", "app_secret": "secret-value"},
            token_call[2],
        )
        self.assertIn("receive_id_type=open_id", message_call[0])
        self.assertEqual("Bearer token-value", message_call[1]["Authorization"])
        self.assertEqual("ou_target1234", message_call[2]["receive_id"])
        self.assertEqual("text", message_call[2]["msg_type"])
        self.assertEqual(
            {"text": '中文 "quoted"\nnext line'},
            json.loads(message_call[2]["content"]),
        )

    def test_retries_network_failure_with_exponential_backoff(self):
        delays = []
        transport = FakeTransport(
            [
                NetworkFailure("temporary"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        client.send_text("hello")
        self.assertEqual([1.0], delays)

    def test_retries_http_429_and_5xx_at_most_twice(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(429, {"code": 230020, "msg": "rate limited"}),
                JsonResponse(503, {"code": -1, "msg": "unavailable"}),
                JsonResponse(503, {"code": -1, "msg": "unavailable"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        with self.assertRaisesRegex(ConnectorError, "after 3 attempts") as caught:
            client.fetch_tenant_access_token()
        self.assertTrue(caught.exception.retryable)
        self.assertEqual([1.0, 2.0], delays)
        self.assertEqual(3, len(transport.calls))

    def test_retries_feishu_rate_limit_business_code(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 230020, "msg": "rate limited"}),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        self.assertEqual("token-value", client.fetch_tenant_access_token())
        self.assertEqual([1.0], delays)

    def test_does_not_retry_permission_or_recipient_error(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(400, {"code": 230013, "msg": "no availability"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        with self.assertRaises(ConnectorError) as caught:
            client.send_text("hello")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(230013, caught.exception.code)
        self.assertEqual([], delays)
        self.assertEqual(2, len(transport.calls))

    def test_empty_token_is_authentication_error(self):
        transport = FakeTransport([JsonResponse(200, {"code": 0})])
        client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
        with self.assertRaisesRegex(ConnectorError, "missing tenant_access_token"):
            client.fetch_tenant_access_token()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the client tests and confirm the expected import failure**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_client.py' -v
```

Expected: FAIL because `ConnectorError`, `FeishuClient`, `JsonResponse`, and `NetworkFailure` do not exist.

- [ ] **Step 3: Add the HTTP response and error types**

Append these imports and definitions to `feishu-connector/scripts/feishu_notify.py`; keep all imports together at the top of the file:

```python
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


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
```

There must be only one `from dataclasses import dataclass` import after consolidating imports.

- [ ] **Step 4: Implement the standard-library JSON transport**

Add:

```python
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
        return JsonResponse(exc.code, _decode_response(exc.read()))
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise NetworkFailure("Feishu request failed") from exc
```

Do not include the URL, headers, payload, Secret, Token, or Open ID in `NetworkFailure`.

- [ ] **Step 5: Implement authentication, sending, and retry classification**

Add:

```python
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
```

- [ ] **Step 6: Run the configuration and client tests**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

Expected: 14 tests pass with no network requests.

- [ ] **Step 7: Commit the Feishu client**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_client.py
git commit -m "feat: send Feishu bot messages"
```

---

### Task 3: CLI commands, task template, and automatic-notification gate

**Files:**
- Modify: `feishu-connector/scripts/feishu_notify.py`
- Create: `feishu-connector/tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `auto_notify_enabled`, `FeishuClient`, `ConfigError`, and `ConnectorError`.
- Produces: `build_parser()`, `render_task_message(source, status, task, summary, repo, branch)`, and `main(argv, environ, env_file, client_factory, stdout, stderr)`.
- Exit codes: `0` success or auto-disabled no-op; `2` argparse input error; `3` configuration error; `4` non-transient Feishu/auth/permission/recipient error; `5` exhausted network/rate-limit/server error.
- The `task --auto` flag is the safe Skill-facing gate: when auto notification is disabled, it exits `0` without validating credentials or making HTTP requests.

- [ ] **Step 1: Write failing CLI tests**

Create `feishu-connector/tests/test_cli.py`:

```python
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from feishu_notify import ConnectorError, main, render_task_message  # noqa: E402


class FakeClient:
    sent = []
    error = None

    def __init__(self, config):
        self.config = config

    def send_text(self, message):
        if self.error is not None:
            raise self.error
        self.sent.append(message)


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeClient.sent = []
        FakeClient.error = None
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env_file = Path(directory.name) / ".env"
        self.env_file.write_text(
            "FEISHU_APP_ID=cli_test\n"
            "FEISHU_APP_SECRET=test-secret\n"
            "FEISHU_RECEIVE_OPEN_ID=ou_test1234\n"
            "FEISHU_AUTO_NOTIFY=true\n",
            encoding="utf-8",
        )

    def invoke(self, argv, environ=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=argv,
            environ={} if environ is None else environ,
            env_file=self.env_file,
            client_factory=FakeClient,
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_send_sends_exact_plain_text(self):
        code, stdout, stderr = self.invoke(["send", "--message", "hello 飞书"])
        self.assertEqual(0, code)
        self.assertEqual(["hello 飞书"], FakeClient.sent)
        self.assertIn("sent", stdout)
        self.assertEqual("", stderr)

    def test_task_renders_fixed_five_field_template(self):
        code, _, _ = self.invoke(
            [
                "task",
                "--status", "success",
                "--task", "修复登录问题",
                "--summary", "测试已通过",
                "--repo", "harness-craft",
                "--branch", "feishu",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual(
            "[Codex] SUCCESS\n"
            "任务：修复登录问题\n"
            "摘要：测试已通过\n"
            "仓库：harness-craft\n"
            "分支：feishu",
            FakeClient.sent[0],
        )

    def test_auto_task_is_noop_when_disabled(self):
        self.env_file.write_text("FEISHU_AUTO_NOTIFY=false\n", encoding="utf-8")
        code, stdout, stderr = self.invoke(
            [
                "task", "--auto",
                "--status", "success",
                "--task", "task",
                "--summary", "summary",
                "--repo", "repo",
                "--branch", "branch",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual([], FakeClient.sent)
        self.assertIn("disabled", stdout)
        self.assertEqual("", stderr)

    def test_explicit_send_ignores_auto_notify_setting(self):
        self.env_file.write_text(
            "FEISHU_APP_ID=cli_test\n"
            "FEISHU_APP_SECRET=test-secret\n"
            "FEISHU_RECEIVE_OPEN_ID=ou_test1234\n"
            "FEISHU_AUTO_NOTIFY=false\n",
            encoding="utf-8",
        )
        code, _, _ = self.invoke(["send", "--message", "explicit"])
        self.assertEqual(0, code)
        self.assertEqual(["explicit"], FakeClient.sent)

    def test_config_error_returns_3_without_leaking_secret(self):
        self.env_file.write_text("FEISHU_APP_ID=cli_test\n", encoding="utf-8")
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(3, code)
        self.assertIn("FEISHU_APP_SECRET", stderr)
        self.assertNotIn("ou_test1234", stderr)

    def test_non_transient_api_error_returns_4_and_code(self):
        FakeClient.error = ConnectorError("api", "Feishu business error", code=230013)
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(4, code)
        self.assertIn("230013", stderr)
        self.assertNotIn("test-secret", stderr)
        self.assertNotIn("ou_test1234", stderr)

    def test_exhausted_transient_error_returns_5(self):
        FakeClient.error = ConnectorError(
            "network",
            "Feishu network request failed after 3 attempts",
            retryable=True,
        )
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(5, code)
        self.assertIn("network", stderr)

    def test_render_rejects_empty_task_fields(self):
        with self.assertRaisesRegex(ValueError, "summary"):
            render_task_message("Codex", "success", "task", "", "repo", "branch")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run CLI tests and confirm the expected import failure**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
```

Expected: FAIL because `main` and `render_task_message` do not exist.

- [ ] **Step 3: Implement argument parsing and task rendering**

Add `argparse` and `sys` to the imports, then add:

```python
EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_REMOTE = 4
EXIT_TRANSIENT = 5


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
```

- [ ] **Step 4: Implement the CLI orchestration and exit-code mapping**

Add:

```python
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
```

Do not catch `argparse`'s `SystemExit`; malformed CLI input must retain exit code `2` and show normal argparse help.

- [ ] **Step 5: Run all unit tests and CLI help smoke tests**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
python3 feishu-connector/scripts/feishu_notify.py --help
python3 feishu-connector/scripts/feishu_notify.py send --help
python3 feishu-connector/scripts/feishu_notify.py task --help
```

Expected: 22 tests pass; all three help commands exit `0` and document required arguments without printing secrets.

- [ ] **Step 6: Commit the CLI contract**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_cli.py
git commit -m "feat: add Feishu notification CLI"
```

---

### Task 4: Thin Codex Skill adapter

**Files:**
- Create: `feishu-connector/skills/feishu-notify/SKILL.md`
- Create: `feishu-connector/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: the exact `send --message` and `task --auto` CLI contracts from Task 3.
- Produces: a project-installable `feishu-notify` Skill with explicit-send and automatic-task workflows.
- The Skill must treat an automatic notification as secondary and preserve the original result when the CLI exits nonzero.

- [ ] **Step 1: Invoke the required Skill-authoring guidance**

Before editing files, invoke and read:

```text
skill-creator
superpowers:writing-skills
```

Apply their current validation requirements. If they conflict with this plan, the approved product behavior in `feishu-connector/specs/feishu-connector.md` takes precedence; document any formatting-only adjustment in the task review.

- [ ] **Step 2: Write the failing Skill contract test**

Create `feishu-connector/tests/test_skill_contract.py`:

```python
import unittest
from pathlib import Path


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "feishu-notify"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_has_expected_frontmatter_name(self):
        self.assertIn("name: feishu-notify", self.skill)

    def test_explicit_send_uses_send_subcommand(self):
        self.assertIn("feishu_notify.py send --message", self.skill)

    def test_automatic_send_uses_task_auto_gate(self):
        self.assertIn("feishu_notify.py task --auto", self.skill)

    def test_requires_all_five_task_fields(self):
        for argument in ("--status", "--task", "--summary", "--repo", "--branch"):
            self.assertIn(argument, self.skill)

    def test_prohibits_full_results_logs_diffs_and_reasoning(self):
        for phrase in ("完整最终回复", "完整日志", "Diff", "内部推理"):
            self.assertIn(phrase, self.skill)

    def test_notification_failure_preserves_original_task_result(self):
        self.assertIn("不得改变原任务结果", self.skill)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the Skill test and confirm the expected file error**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
```

Expected: ERROR with `FileNotFoundError` for `skills/feishu-notify/SKILL.md`.

- [ ] **Step 4: Create the thin Skill**

Create `feishu-connector/skills/feishu-notify/SKILL.md` with this behavior, adapting only frontmatter or structural formatting if the Skill-authoring guidance requires it:

```markdown
---
name: feishu-notify
description: Send an explicit plain-text Feishu message when the user asks, or send a configured task-completion notification after a Codex task finishes.
---

# Feishu Notify

Use the repository's `feishu-connector/scripts/feishu_notify.py` CLI. Do not implement Feishu HTTP requests in this Skill, do not read or print App Secret or access tokens, and do not send messages unless one of the workflows below applies.

## Explicit message workflow

When the user explicitly asks to send text to Feishu:

1. Use exactly the text the user designated for sending. Do not attach source code, logs, Diff, or other context unless the user explicitly included it.
2. Run:

   ```bash
   python3 feishu-connector/scripts/feishu_notify.py send --message "<user-designated text>"
   ```

3. Report whether the CLI succeeded. If it failed, report the CLI's redacted warning without exposing configuration values.

This workflow does not depend on `FEISHU_AUTO_NOTIFY`.

## Automatic task-completion workflow

Use this workflow only when repository instructions enable it and the current task is about to return its final result. Run it at most once per final task result.

1. Derive:
   - `status`: `success` only when the original task succeeded; otherwise `failure`.
   - `task`: a short name based on the user's request.
   - `summary`: one short outcome summary. Never send the 完整最终回复、完整日志、Diff、内部推理, secrets, tokens, or unrelated context.
   - `repo`: the current Git repository directory name, or the current directory name outside Git.
   - `branch`: `git branch --show-current`; use `detached` if it is empty.
2. Run the CLI's safe configuration gate:

   ```bash
   python3 feishu-connector/scripts/feishu_notify.py task --auto --status success --task "<task>" --summary "<summary>" --repo "<repo>" --branch "<branch>"
   ```

   Replace `success` with `failure` when appropriate.
3. If the command reports that automatic notification is disabled, do not send anything and do not mention an error.
4. If sending fails, append one short redacted warning to the original final response. 通知失败不得改变原任务结果，也不得覆盖原失败原因或 trigger another work cycle.
```

- [ ] **Step 5: Run Skill contract and authoring validation**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

Expected: 6 Skill tests pass and the complete suite reports 28 passing tests. Also run the validation command required by the current `skill-creator` or `superpowers:writing-skills` guidance; it must exit `0`.

- [ ] **Step 6: Commit the Codex adapter**

```bash
git add feishu-connector/skills/feishu-notify/SKILL.md feishu-connector/tests/test_skill_contract.py
git commit -m "feat: add Codex Feishu notification skill"
```

---

### Task 5: User documentation and complete Phase 1 verification

**Files:**
- Create: `feishu-connector/README.md`
- Modify only if verification finds a defect: Phase 1 files listed in the File Map.

**Interfaces:**
- Consumes: the complete CLI and Skill contracts from Tasks 1–4.
- Produces: an operator-facing setup and acceptance guide that never contains real credentials.
- This task does not add Phase 2 JSON configuration or OpenCode implementation.

- [ ] **Step 1: Write README contract assertions before the README exists**

Append this class to `feishu-connector/tests/test_skill_contract.py`:

```python
class ReadmeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (
            Path(__file__).resolve().parents[1] / "README.md"
        ).read_text(encoding="utf-8")

    def test_documents_feishu_admin_prerequisites(self):
        for phrase in ("企业自建应用", "机器人能力", "im:message:send_as_bot", "可用范围"):
            self.assertIn(phrase, self.readme)

    def test_documents_configuration_and_both_commands(self):
        for phrase in (
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_RECEIVE_OPEN_ID",
            "FEISHU_AUTO_NOTIFY",
            "feishu_notify.py send",
            "feishu_notify.py task",
        ):
            self.assertIn(phrase, self.readme)

    def test_documents_failure_isolation_and_offline_tests(self):
        self.assertIn("不会改变原任务结果", self.readme)
        self.assertIn("不访问真实飞书", self.readme)

    def test_marks_json_configuration_as_phase_two(self):
        self.assertIn("二期", self.readme)
        self.assertIn("config.json", self.readme)
        self.assertIn("一期不读取", self.readme)
```

- [ ] **Step 2: Run the README contract tests and confirm the expected file error**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
```

Expected: the 6 existing Skill tests pass and the README contract setup errors with `FileNotFoundError`.

- [ ] **Step 3: Create the user-facing README**

Create `feishu-connector/README.md` with these exact sections and content requirements:

```markdown
# 飞书消息连接器

## 能力边界

说明一期使用企业自建应用机器人向一个固定 Open ID 发送纯文本私聊；不使用群机器人 Webhook，不收消息，不支持群聊、富文本、多用户或动态接收人。

## 飞书端准备

逐步说明创建企业自建应用、开启机器人能力、申请 `im:message:send_as_bot` 最小权限、把目标用户加入可用范围、发布版本，以及取得 App ID、App Secret 和该应用下的 Open ID。

## 本地配置

说明复制 `.env.example` 为 `.env`，填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY`。强调 `.env` 已被 Git 忽略，Secret 不得出现在命令行、日志或提交中；环境变量覆盖 `.env` 同名值。

## 手动发送

提供 `python3 feishu-connector/scripts/feishu_notify.py send --message "测试消息"`，并说明显式发送不受自动通知开关影响。

## 任务通知

提供完整 `task` 示例和 `task --auto` 示例，解释五个字段、`success|failure`、固定纯文本格式，以及关闭自动通知时 `--auto` 是成功但不发送的 no-op。

## Codex Skill

说明如何让 Codex 读取 `feishu-connector/skills/feishu-notify/SKILL.md`，以及项目指令必须明确启用自动任务通知约定。说明通知失败只追加脱敏警告，不会改变原任务结果。

## 测试

给出 `python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v`，说明默认测试通过 Mock 运行，不访问真实飞书或读取真实凭据。

## 手动端到端验收

列出：测试 `send`、测试 `task` 五字段、分别验证自动开关、用无效 Open ID 验证脱敏与原任务状态隔离。要求使用测试应用和测试用户。

## 排错

按配置错误、鉴权/权限、用户不在可用范围、用户拒收、限流/网络/服务端错误解释退出码 3、4、5 和最多两次额外重试。禁止建议打印 Secret、Token、Authorization 或完整 Open ID。

## 二期

说明 `~/.config/feishu-connector/config.json` 与项目 `.config/feishu-connector/config.json` 属于已批准的二期范围，一期不读取任何 `config.json`。
```

Replace each instructional paragraph with polished user-facing Chinese prose while preserving every named command, setting, permission, behavior, and boundary. Do not include real IDs, secrets, tenant names, or screenshots.

- [ ] **Step 4: Run the complete offline verification suite**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
python3 feishu-connector/scripts/feishu_notify.py --help
python3 feishu-connector/scripts/feishu_notify.py send --help
python3 feishu-connector/scripts/feishu_notify.py task --help
git check-ignore -q --no-index feishu-connector/.env
git diff --check
```

Expected: 32 tests pass; all help commands exit `0`; `.env` is ignored; `git diff --check` is silent. No command contacts Feishu.

- [ ] **Step 5: Perform a requirements audit against the approved spec**

Read `feishu-connector/specs/feishu-connector.md` Sections 2.1, 2.3, 4–13 and verify each Phase 1 item maps to code, a test, or README guidance. Explicitly record these checks in the task review:

```text
fixed-user plain text: code + client/CLI tests
manual CLI: send test + README
Codex explicit send: Skill contract
configured automatic notification: --auto CLI tests + Skill contract
five-field template: CLI test + README
failure isolation: exit mapping + Skill/README contract
standard library only: dependency inspection
offline default tests: full unittest run
secret/token/Open ID handling: config/client/CLI tests + README
future OpenCode reuse: --source enum + adapter-free client boundary
Phase 2 excluded: no config.json reader or OpenCode Skill
```

If any item lacks evidence, add the smallest failing test, implement only the missing Phase 1 behavior, rerun the focused test, then rerun Step 4.

- [ ] **Step 6: Commit documentation and final Phase 1 adjustments**

```bash
git add feishu-connector/README.md feishu-connector/tests/test_skill_contract.py
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_config.py feishu-connector/tests/test_client.py feishu-connector/tests/test_cli.py
git commit -m "docs: add Feishu connector usage guide"
```

- [ ] **Step 7: Run post-commit verification**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
git status --short --branch
git log -7 --oneline --decorate
```

Expected: 32 tests pass, the working tree is clean, and the latest seven commits include the approved specification and implementation-plan commits followed by the five focused Phase 1 task commits from this plan.

The live Feishu end-to-end check remains an explicit user-run acceptance step because it transmits a message and requires real credentials. Do not run it during default verification or without the user's action-time authorization.

## Plan Deviations (recorded during implementation)

| # | Deviation | Rationale | Approved |
|---|-----------|-----------|----------|
| 1 | `feishu_notify_adapter.py` introduced outside File Map (commit 984aba4) | Security hardening: plan's `--message "<user-designated text>"` template is a shell injection vector. Adapter uses JSON stdin + `subprocess.run(argv, shell=False)` to eliminate shell injection. Not in plan File Map but is a safe zero-cost addition. | 三方仲裁确认合理 |
| 2 | `post_json` HTTPError body-read exception widened from `IncompleteRead` to `HTTPException` (commit 85b6d5e) | `LineTooLong` and other `HTTPException` subclasses would bypass the error handler and crash with traceback + exit 1. | 合并前修复 |
| 3 | `post_json` success-path exception widened from `IncompleteRead` to `HTTPException` (commit after review) | Symmetric fix: `BadStatusLine` from `urlopen` itself would escape error classification. | 合并前修复 |
| 4 | Adapter `subprocess.run` wrapped in `try/except (OSError, ValueError, UnicodeError)` (commit after review) | `\u0000` → `ValueError`, lone surrogate → `UnicodeEncodeError`, oversized input → `OSError(E2BIG)`. Without this, adapter crashes with traceback + exit 1, violating the stable-error contract. | 合并前修复 |
