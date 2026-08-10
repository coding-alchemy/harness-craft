# Feishu Connector Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Feishu message retries idempotent, expose redacted retry diagnostics in CLI execution, and reject invalid Unicode command arguments before configuration or network access.

**Architecture:** Keep the existing `FeishuClient`, argparse CLI, exit codes, and configuration subsystem. Add one UUID per logical `send_text()` call, validate free-text argv through the existing argparse type hook, and scope a logging handler to each `main()` invocation so library imports remain quiet.

**Tech Stack:** Python 3 standard library (`argparse`, `logging`, `uuid`, `unittest`, `subprocess`); no third-party packages and no live Feishu requests.

## Global Constraints

- Configuration precedence remains environment variables > project JSON > global JSON, merged by leaf field.
- Project JSON must continue to reject `appSecret`; secrets may only come from environment variables or global JSON.
- Preserve `send`, `task`, `task --auto`, `config`, `--source OpenCode`, and exit codes `0`, `2`, `3`, `4`, `5`.
- Automatic notification failure must not change the original task result.
- Use only Python 3 standard library code and offline tests.
- Never print App Secret, Tenant Access Token, Authorization, full Open ID, request headers, or complete request bodies.
- Every production change follows red-green-refactor: add a focused failing test, observe the expected failure, implement the minimum behavior, then run the focused and full suites.

---

### Task 1: Add idempotency UUIDs to message retries

**Files:**
- Modify: `feishu-connector/tests/test_client.py`
- Modify: `feishu-connector/scripts/feishu_notify.py:7-15,117-129,219-236`

**Interfaces:**
- Consumes: existing `FeishuClient(config, transport, sleep, timeout, max_retries)` and `FakeTransport` test seam.
- Produces: `FeishuClient(..., uuid_factory=uuid.uuid4)`; each `send_text(message)` includes one stable string UUID in all retried message payloads.

- [ ] **Step 1: Write failing idempotency tests**

Add these methods to `ClientTests` in `feishu-connector/tests/test_client.py`:

```python
    def test_message_retry_reuses_one_idempotency_uuid(self):
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                NetworkFailure("response lost after possible delivery"),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(
            self.config(),
            transport=transport,
            sleep=lambda _: None,
            uuid_factory=lambda: "logical-send-uuid",
        )

        client.send_text("hello")

        message_calls = [call for call in transport.calls if "/messages?" in call[0]]
        self.assertEqual(2, len(message_calls))
        self.assertEqual("logical-send-uuid", message_calls[0][2]["uuid"])
        self.assertEqual("logical-send-uuid", message_calls[1][2]["uuid"])

    def test_separate_logical_sends_use_different_uuids(self):
        identifiers = iter(("first-send-uuid", "second-send-uuid"))
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-one"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-two"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(
            self.config(),
            transport=transport,
            sleep=lambda _: None,
            uuid_factory=lambda: next(identifiers),
        )

        client.send_text("first")
        client.send_text("second")

        message_calls = [call for call in transport.calls if "/messages?" in call[0]]
        self.assertEqual(
            ["first-send-uuid", "second-send-uuid"],
            [call[2]["uuid"] for call in message_calls],
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_client.py' -v
```

Expected: both tests error with `TypeError: FeishuClient.__init__() got an unexpected keyword argument 'uuid_factory'`.

- [ ] **Step 3: Implement one UUID per logical send**

In `feishu-connector/scripts/feishu_notify.py`, add the import:

```python
import uuid
```

Extend the constructor without changing existing defaults:

```python
    def __init__(
        self,
        config,
        transport=post_json,
        sleep=time.sleep,
        timeout=10.0,
        max_retries=2,
        uuid_factory=uuid.uuid4,
    ):
        self.config = config
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout
        self.max_retries = max_retries
        self.uuid_factory = uuid_factory
```

Replace `send_text()` with a payload created once outside the retry lambda:

```python
    def send_text(self, message):
        token = self.fetch_tenant_access_token()
        content = json.dumps(
            {"text": message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload = {
            "receive_id": self.config.receive_open_id,
            "msg_type": "text",
            "content": content,
            "uuid": str(self.uuid_factory()),
        }
        return self._attempt(
            lambda: self._post(
                self.MESSAGE_URL,
                {"Authorization": "Bearer %s" % token},
                payload,
            )
        )
```

- [ ] **Step 4: Run focused and client tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_client.py' -v
```

Expected: all client tests pass; the existing request test now also sees a `uuid` field but its assertions about `receive_id`, `msg_type`, and `content` remain valid.

- [ ] **Step 5: Commit the idempotency change**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_client.py
git commit -m "fix: make Feishu message retries idempotent"
```

---

### Task 2: Reject invalid Unicode argv before configuration and network access

**Files:**
- Modify: `feishu-connector/tests/test_cli.py:1-14,31-390`
- Modify: `feishu-connector/scripts/feishu_notify.py:239-242`

**Interfaces:**
- Consumes: argparse `type=non_empty` already used by `--message`, `--task`, `--summary`, `--repo`, and `--branch`.
- Produces: `non_empty(value)` rejects strings that cannot encode to UTF-8 with an ASCII-only `ArgumentTypeError`; real CLI exits `2` before reading configuration.

- [ ] **Step 1: Add real-process invalid argv tests**

Add `os` and `subprocess` imports to `feishu-connector/tests/test_cli.py`:

```python
import os
import subprocess
```

Add this helper and two tests to `CliTests`:

```python
    def run_cli_with_bytes(self, arguments):
        command = [
            os.fsencode(sys.executable),
            os.fsencode(str(SCRIPTS / "feishu_notify.py")),
        ] + arguments
        environment = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", ""),
        }
        return subprocess.run(
            command,
            cwd=self.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
    def test_direct_cli_rejects_non_utf8_send_message_before_configuration(self):
        result = self.run_cli_with_bytes(
            [b"send", b"--message", b"invalid-\xff-text"]
        )
        self.assertEqual(2, result.returncode)
        self.assertIn(b"valid Unicode", result.stderr)
        self.assertNotIn(b"configuration error", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
    def test_direct_cli_rejects_non_utf8_task_field_before_configuration(self):
        result = self.run_cli_with_bytes(
            [
                b"task",
                b"--status", b"success",
                b"--task", b"task",
                b"--summary", b"invalid-\xff-summary",
                b"--repo", b"repo",
                b"--branch", b"branch",
            ]
        )
        self.assertEqual(2, result.returncode)
        self.assertIn(b"valid Unicode", result.stderr)
        self.assertNotIn(b"configuration error", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
```

Expected on POSIX: both tests fail because the current CLI accepts the surrogate-decoded argv and later returns configuration exit code `3` instead of input exit code `2`.

- [ ] **Step 3: Add UTF-8 scalar validation to the existing argparse hook**

Replace `non_empty()` in `feishu-connector/scripts/feishu_notify.py` with:

```python
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
```

Do not echo `value` in the error and do not add Unicode handling after configuration loading; validation must remain in argparse.

- [ ] **Step 4: Run focused and CLI tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
```

Expected: all CLI tests pass; POSIX runs include the two new real-process tests, while unsupported platforms skip them.

- [ ] **Step 5: Commit Unicode validation**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_cli.py
git commit -m "fix: reject invalid Unicode Feishu arguments"
```

---

### Task 3: Expose scoped, redacted retry logs through CLI stderr

**Files:**
- Modify: `feishu-connector/tests/test_cli.py:12,31-390`
- Modify: `feishu-connector/scripts/feishu_notify.py:303-375`

**Interfaces:**
- Consumes: module-level `LOGGER`, `FeishuClient`, `main(..., stderr=stream)`, and existing retry warning format.
- Produces: `_run_main(...)` containing the existing command behavior; public `main(...)` temporarily attaches one `StreamHandler` to its `stderr` and always removes it.

- [ ] **Step 1: Add a failing CLI retry-log test**

Extend the `feishu_notify` import in `feishu-connector/tests/test_cli.py`:

```python
from feishu_notify import (  # noqa: E402
    ConnectorError,
    FeishuClient,
    JsonResponse,
    LOGGER,
    NetworkFailure,
    main,
    render_task_message,
)
```

Add this test to `CliTests`:

```python
    def test_cli_writes_redacted_retry_diagnostics_to_its_stderr(self):
        original_handlers = tuple(LOGGER.handlers)
        outcomes = iter(
            (
                NetworkFailure("temporary test-secret ou_test1234"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            )
        )

        def transport(url, headers, payload, timeout):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def client_factory(config):
            return FeishuClient(config, transport=transport, sleep=lambda _: None)

        code, _, stderr = self.invoke(
            ["send", "--message", "hello"],
            client_factory=client_factory,
        )

        self.assertEqual(0, code)
        self.assertIn("Feishu retry [network] attempt 1/3", stderr)
        self.assertNotIn("test-secret", stderr)
        self.assertNotIn("ou_test1234", stderr)
        self.assertNotIn("token-value", stderr)
        self.assertEqual(original_handlers, tuple(LOGGER.handlers))
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
```

Expected: FAIL because `stderr` is empty; the module currently has only a `NullHandler`.

- [ ] **Step 3: Split command execution from scoped logging**

Rename the current `main` implementation to `_run_main` while preserving its existing parameters and body. Then add this public wrapper immediately below `_run_main`:

```python
def main(
    argv=None,
    environ=None,
    config_paths=None,
    client_factory=FeishuClient,
    stdout=None,
    stderr=None,
    cwd=None,
    home=None,
    git_runner=subprocess.run,
):
    stderr = sys.stderr if stderr is None else stderr
    handler = logging.StreamHandler(stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    try:
        return _run_main(
            argv=argv,
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
        handler.close()
```

Keep `_run_main`'s default `client_factory=FeishuClient`; the wrapper must pass every argument by name so existing tests and embedders keep the same public signature. Do not set a global logging level or root handler.

- [ ] **Step 4: Run focused, CLI, and client tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_client.py' -v
```

Expected: both files pass; retry logs appear only in the `stderr` belonging to the invoking `main()` call.

- [ ] **Step 5: Commit scoped retry diagnostics**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_cli.py
git commit -m "fix: expose Feishu retry diagnostics"
```

---

### Task 4: Synchronize connector documentation and run the hardening gate

**Files:**
- Modify: `feishu-connector/README.md:83-153`
- Modify: `feishu-connector/docs/USAGE.md:71-89`
- Verify: `feishu-connector/specs/feishu-connector.md:504-553`

**Interfaces:**
- Consumes: stable UUID behavior, argparse input exit `2`, and CLI retry logging from Tasks 1-3.
- Produces: user-facing troubleshooting text consistent with the hardened connector and a fully verified hardening checkpoint.

- [ ] **Step 1: Update README reliability text**

In the troubleshooting section of `feishu-connector/README.md`, replace the final retry paragraph with:

```markdown
退出码 `5` 表示临时性失败，例如网络中断、限流、服务端错误。连接器会在首次失败后最多额外重试两次，因此单个请求阶段最多尝试三次。消息请求在一次逻辑发送的所有重试中复用同一个幂等 UUID，避免响应丢失造成重复私聊。

CLI 会把每次重试的脱敏错误类别和尝试次数写到 stderr。排错时不要打印 Secret、Token、Authorization、完整 Open ID、请求头或完整请求体。

无法编码为 UTF-8 的消息或任务字段属于参数错误，CLI 会在读取配置和联网前以退出码 `2` 拒绝。
```

- [ ] **Step 2: Update quick-usage troubleshooting text**

After the exit-code table in `feishu-connector/docs/USAGE.md`, replace its retry paragraph with:

```markdown
网络、限流和服务端错误在每个请求阶段最多额外重试两次。消息阶段的重试复用同一个幂等 UUID；CLI stderr 只显示脱敏的错误类别和尝试次数。非法 Unicode 文本在读取配置和联网前按参数错误返回退出码 `2`。完整排错说明和手动端到端验收步骤见 [README](../README.md)。
```

- [ ] **Step 3: Run the full offline test suite**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

Expected: all tests pass; the count is the previous 81 plus five new tests (expected 86, except capability skips remain reported as skips rather than failures).

- [ ] **Step 4: Run syntax, CLI, dependency, and diff gates**

Run:

```bash
python3 -m compileall -q feishu-connector/scripts feishu-connector/tests
python3 feishu-connector/scripts/feishu_notify.py --help
python3 feishu-connector/scripts/feishu_notify.py send --help
python3 feishu-connector/scripts/feishu_notify.py task --help
python3 feishu-connector/scripts/feishu_notify.py config --help
git diff --check
git status --short --branch
```

Expected: compilation and every help command exit `0`; help lists the existing public arguments; `git diff --check` is silent; status lists only the intended hardening and documentation changes.

- [ ] **Step 5: Confirm standard-library-only imports and secret hygiene**

Run:

```bash
rg -n '^(from|import) ' feishu-connector/scripts feishu-connector/tests
rg -n 'test-secret|token-value|ou_test1234' \
  feishu-connector/README.md \
  feishu-connector/docs/USAGE.md \
  feishu-connector/specs/feishu-connector.md \
  feishu-connector/specs/2026-08-07-feishu-usage-guide-design.md \
  feishu-connector/specs/2026-08-08-feishu-connector-installer-design.md
```

Expected: implementation imports resolve to Python standard library or local connector modules; real user documentation/specs contain none of the test-only credential strings.

- [ ] **Step 6: Commit documentation and verification checkpoint**

```bash
git add feishu-connector/README.md feishu-connector/docs/USAGE.md
git commit -m "docs: describe Feishu reliability hardening"
```
