import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = CONNECTOR_ROOT / "skills" / "feishu-notify" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from feishu_connector import cli  # noqa: E402
from feishu_connector.client import (  # noqa: E402
    ConnectorError,
    FeishuClient,
    JsonResponse,
    LOGGER,
    NetworkFailure,
)
from feishu_connector.cli import main, render_task_card  # noqa: E402
from feishu_connector.config import ConfigPaths  # noqa: E402


class FakeClient:
    sent_text = []
    sent_cards = []
    configs = []
    error = None

    def __init__(self, config):
        self.config = config
        self.configs.append(config)

    def send_text(self, message):
        if self.error is not None:
            raise self.error
        self.sent_text.append(message)

    def send_card(self, card):
        if self.error is not None:
            raise self.error
        self.sent_cards.append(card)


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeClient.sent_text = []
        FakeClient.sent_cards = []
        FakeClient.configs = []
        FakeClient.error = None
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.global_file = self.root / "global.json"
        self.project_file = self.root / "project.json"
        self.global_file.write_text(
            json.dumps(
                {
                    "app": {
                        "appId": "cli_test",
                        "appSecret": "test-secret",
                    },
                    "recipient": {"openId": "ou_test1234"},
                    "notification": {"autoNotify": True},
                }
            ),
            encoding="utf-8",
        )
        self.global_file.chmod(0o600)
        self.config_paths = ConfigPaths(
            global_file=self.global_file,
            project_file=self.project_file,
        )

    def invoke(self, argv, environ=None, client_factory=FakeClient, stdin=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=argv,
            environ={} if environ is None else environ,
            config_paths=self.config_paths,
            client_factory=client_factory,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def run_cli_with_bytes(self, arguments):
        command = [
            os.fsencode(sys.executable),
            os.fsencode(str(SKILL_SCRIPTS / "feishu_notify.py")),
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

    def test_send_sends_exact_plain_text(self):
        code, stdout, stderr = self.invoke(["send", "--message", "hello 飞书"])
        self.assertEqual(0, code)
        self.assertEqual(["hello 飞书"], FakeClient.sent_text)
        self.assertEqual([], FakeClient.sent_cards)
        self.assertIn("sent", stdout)
        self.assertEqual("", stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
    def test_direct_cli_rejects_non_utf8_send_message_before_configuration(self):
        result = self.run_cli_with_bytes(
            [b"send", b"--message", b"invalid-\xff-text"]
        )
        self.assertEqual(2, result.returncode)
        self.assertIn(b"valid Unicode", result.stderr)
        self.assertNotIn(b"configuration error", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_render_task_card_uses_exact_title_color_and_markdown(self):
        self.assertEqual(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "green",
                    "title": {
                        "tag": "plain_text",
                        "content": "HETU-个股-二期-架构师-任务完成",
                    },
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**结果**\n\n- 评审通过",
                        },
                    }
                ],
            },
            render_task_card(
                "success", "HETU", "个股-二期-架构师", "**结果**\n\n- 评审通过"
            ),
        )

    def test_render_task_card_maps_all_statuses(self):
        for status, label, color in (
            ("success", "任务完成", "green"),
            ("failure", "任务失败", "red"),
            ("confirm", "待确认", "orange"),
        ):
            with self.subTest(status=status):
                card = render_task_card(status, "项目", "对话", "正文")
                self.assertEqual(
                    "项目-对话-" + label, card["header"]["title"]["content"]
                )
                self.assertEqual(color, card["header"]["template"])

    def test_render_task_card_rejects_invalid_status(self):
        for status in ("cancel", "SUCCESS", "", None):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "status"):
                    render_task_card(status, "项目", "对话", "正文")

    def test_render_task_card_validates_title_fields_and_content(self):
        line_breaks = (
            "\n",
            "\r",
            "\v",
            "\f",
            "\x1c",
            "\x1d",
            "\x1e",
            "\x85",
            "\u2028",
            "\u2029",
        )
        for field in ("project", "conversation"):
            for value in ("", "   ", "a\x00b", "\ud800") + tuple(
                "a%sb" % char for char in line_breaks
            ):
                with self.subTest(field=field, value=repr(value)):
                    arguments = {
                        "status": "success",
                        "project": "项目",
                        "conversation": "对话",
                        "content": "正文",
                    }
                    arguments[field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        render_task_card(**arguments)
        for value in ("", "   ", "a\x00b", "\ud800"):
            with self.subTest(content=repr(value)):
                with self.assertRaisesRegex(ValueError, "content"):
                    render_task_card("success", "项目", "对话", value)
        multiline = "第一行\n第二行\u2028第三行"
        card = render_task_card("success", "项目", "对话", multiline)
        self.assertEqual(multiline, card["elements"][0]["text"]["content"])

    def test_task_sends_card_and_explicit_send_stays_plain_text(self):
        code, _, stderr = self.invoke(
            [
                "task",
                "--status",
                "success",
                "--project",
                "HETU",
                "--conversation",
                "个股",
                "--content",
                "- 完成",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual(1, len(FakeClient.sent_cards))
        self.assertEqual([], FakeClient.sent_text)
        self.assertEqual("", stderr)

        code, _, stderr = self.invoke(["send", "--message", "hello 飞书"])
        self.assertEqual(0, code)
        self.assertEqual(["hello 飞书"], FakeClient.sent_text)
        self.assertEqual(1, len(FakeClient.sent_cards))
        self.assertEqual("", stderr)

    def test_explicit_send_keeps_existing_nul_behavior(self):
        code, _, stderr = self.invoke(["send", "--message", "a\x00b"])
        self.assertEqual(0, code)
        self.assertEqual(["a\x00b"], FakeClient.sent_text)
        self.assertEqual("", stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
    def test_old_task_parameters_have_no_compatibility_layer(self):
        result = self.run_cli_with_bytes(
            [
                b"task",
                b"--status",
                b"success",
                b"--task",
                b"old",
                b"--summary",
                b"old",
                b"--repo",
                b"repo",
                b"--branch",
                b"branch",
                b"--source",
                b"Codex",
            ]
        )
        self.assertEqual(2, result.returncode)

    @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
    def test_direct_cli_rejects_non_utf8_new_task_fields_before_configuration(self):
        for invalid_field in ("project", "conversation", "content"):
            values = {
                "project": b"project",
                "conversation": b"conversation",
                "content": b"content",
            }
            values[invalid_field] = b"invalid-\xff"
            with self.subTest(field=invalid_field):
                result = self.run_cli_with_bytes(
                    [
                        b"task",
                        b"--status",
                        b"success",
                        b"--project",
                        values["project"],
                        b"--conversation",
                        values["conversation"],
                        b"--content",
                        values["content"],
                    ]
                )
                self.assertEqual(2, result.returncode)
                self.assertIn(b"valid Unicode", result.stderr)
                self.assertNotIn(b"configuration error", result.stderr)

    def test_auto_task_is_noop_when_disabled(self):
        self.global_file.write_text(
            json.dumps({"notification": {"autoNotify": False}}), encoding="utf-8"
        )
        code, stdout, stderr = self.invoke(
            [
                "task", "--auto",
                "--status", "success",
                "--project", "project",
                "--conversation", "conversation",
                "--content", "content",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual([], FakeClient.sent_text)
        self.assertEqual([], FakeClient.sent_cards)
        self.assertIn("disabled", stdout)
        self.assertEqual("", stderr)

    def test_auto_environment_false_overrides_json_true_without_client(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("disabled auto task constructed a client")

        code, stdout, stderr = self.invoke(
            [
                "task", "--auto",
                "--status", "success",
                "--project", "project",
                "--conversation", "conversation",
                "--content", "content",
            ],
            environ={"FEISHU_AUTO_NOTIFY": "false"},
            client_factory=ClientMustNotStart,
        )
        self.assertEqual(0, code)
        self.assertIn("disabled", stdout)
        self.assertEqual("", stderr)

    def test_auto_task_uses_one_configuration_snapshot(self):
        original_resolve = cli.resolve_settings

        def change_after_resolution(paths, environ):
            settings = original_resolve(paths, environ)
            self.global_file.write_text(
                json.dumps(
                    {
                        "app": {"appId": "cli_test", "appSecret": "test-secret"},
                        "recipient": {"openId": "ou_test1234"},
                        "notification": {"autoNotify": False},
                    }
                ),
                encoding="utf-8",
            )
            return settings

        with mock.patch(
            "feishu_connector.cli.resolve_settings",
            side_effect=change_after_resolution,
        ) as resolver:
            code, _, stderr = self.invoke(
                [
                    "task", "--auto",
                    "--status", "success",
                    "--project", "project",
                    "--conversation", "conversation",
                    "--content", "content",
                ]
            )
        self.assertEqual(1, resolver.call_count)
        self.assertEqual(0, code)
        self.assertTrue(FakeClient.configs[-1].auto_notify)
        self.assertEqual("", stderr)

    def test_explicit_send_ignores_auto_notify_setting(self):
        self.global_file.write_text(
            json.dumps(
                {
                    "app": {"appId": "cli_test", "appSecret": "test-secret"},
                    "recipient": {"openId": "ou_test1234"},
                    "notification": {"autoNotify": False},
                }
            ),
            encoding="utf-8",
        )
        code, _, _ = self.invoke(["send", "--message", "explicit"])
        self.assertEqual(0, code)
        self.assertEqual(["explicit"], FakeClient.sent_text)

    def test_config_error_returns_3_without_leaking_secret(self):
        self.global_file.write_text(
            json.dumps({"app": {"appId": "cli_test"}}), encoding="utf-8"
        )
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(3, code)
        self.assertIn("app.appSecret", stderr)
        self.assertNotIn("ou_test1234", stderr)

    def test_malformed_json_encoding_returns_3_without_leaking_secret(self):
        self.global_file.write_bytes(b'{"app":{"appSecret":"top-secret"}}\xff')
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(3, code)
        self.assertIn("Feishu configuration error", stderr)
        self.assertNotIn("top-secret", stderr)

    def test_config_command_reports_sources_without_network_or_values(self):
        self.project_file.write_text(
            json.dumps(
                {
                    "recipient": {"openId": "ou_project_hidden"},
                    "notification": {"autoNotify": False},
                }
            ),
            encoding="utf-8",
        )

        class NetworkMustNotStart:
            def __init__(self, config):
                raise AssertionError("diagnostics instantiated the client")

        code, stdout, stderr = self.invoke(
            ["config"],
            environ={"FEISHU_APP_ID": "cli_environment_hidden"},
            client_factory=NetworkMustNotStart,
        )
        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        self.assertIn("app.appId: environment", stdout)
        self.assertIn("app.appSecret: global (redacted)", stdout)
        self.assertIn("recipient.openId: project (redacted)", stdout)
        self.assertIn("notification.autoNotify: project", stdout)
        for hidden in (
            "cli_environment_hidden",
            "test-secret",
            "ou_project_hidden",
        ):
            self.assertNotIn(hidden, stdout)

    def test_invalid_project_secret_returns_3_before_network(self):
        self.project_file.write_text(
            json.dumps({"app": {"appSecret": "forbidden-project-secret"}}),
            encoding="utf-8",
        )

        class NetworkMustNotStart:
            def __init__(self, config):
                raise AssertionError("client started before configuration validation")

        code, _, stderr = self.invoke(
            ["send", "--message", "hello"], client_factory=NetworkMustNotStart
        )
        self.assertEqual(3, code)
        self.assertIn("must not contain app.appSecret", stderr)
        self.assertNotIn("forbidden-project-secret", stderr)

    def test_unresolvable_config_path_returns_3_before_network(self):
        self.config_paths = ConfigPaths(
            global_file=self.root / "global.json",
            project_file=self.project_file,
        )

        class NetworkMustNotStart:
            def __init__(self, config):
                raise AssertionError("client started before path validation")

        with mock.patch(
            "feishu_connector.config.Path.resolve", side_effect=RuntimeError("loop")
        ):
            code, _, stderr = self.invoke(
                ["send", "--message", "hello"], client_factory=NetworkMustNotStart
            )
        self.assertEqual(3, code)
        self.assertTrue(stderr.isascii())

    def test_git_decode_error_returns_3_before_network(self):
        class NetworkMustNotStart:
            def __init__(self, config):
                raise AssertionError("client started before Git validation")

        def git_runner(argv, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\\xff", 0, 1, "invalid")

        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=["send", "--message", "hello"],
            environ={},
            client_factory=NetworkMustNotStart,
            stdout=stdout,
            stderr=stderr,
            cwd=self.root,
            home=self.root,
            git_runner=git_runner,
        )
        self.assertEqual(3, code)
        self.assertTrue(stderr.getvalue().isascii())

    def test_project_root_option_selects_project_json(self):
        project_root = self.root / "selected-project"
        config_file = project_root / ".config" / "feishu-connector" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            json.dumps({"recipient": {"openId": "ou_selected1234"}}),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=["--project-root", str(project_root), "send", "--message", "hello"],
            environ={
                "FEISHU_APP_ID": "cli_environment",
                "FEISHU_APP_SECRET": "environment-secret",
            },
            client_factory=FakeClient,
            stdout=stdout,
            stderr=stderr,
            cwd=self.root,
            home=self.root / "empty-home",
        )
        self.assertEqual(0, code)
        self.assertEqual("ou_selected1234", FakeClient.configs[-1].receive_open_id)
        self.assertEqual("", stderr.getvalue())

    def test_stdin_preserves_explicit_project_root(self):
        selected_project = self.root / "selected-project"
        selected_config = (
            selected_project / ".config" / "feishu-connector" / "config.json"
        )
        selected_config.parent.mkdir(parents=True)
        selected_config.write_text(
            json.dumps({"recipient": {"openId": "ou_selected1234"}}),
            encoding="utf-8",
        )
        wrong_project = self.root / "wrong-project"
        wrong_config = (
            wrong_project / ".config" / "feishu-connector" / "config.json"
        )
        wrong_config.parent.mkdir(parents=True)
        wrong_config.write_text(
            json.dumps({"app": {"appSecret": "must-not-be-read"}}),
            encoding="utf-8",
        )
        global_config = self.root / ".config" / "feishu-connector" / "config.json"
        global_config.parent.mkdir(parents=True)
        global_config.write_text(
            json.dumps(
                {
                    "app": {
                        "appId": "cli_test",
                        "appSecret": "test-secret",
                    }
                }
            ),
            encoding="utf-8",
        )
        global_config.chmod(0o600)
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=["--project-root", str(selected_project), "stdin"],
            environ={},
            client_factory=FakeClient,
            stdin=io.StringIO('{"flow":"send","message":"hello"}'),
            stdout=stdout,
            stderr=stderr,
            cwd=wrong_project,
            home=self.root,
        )
        self.assertEqual(0, code)
        self.assertEqual("ou_selected1234", FakeClient.configs[-1].receive_open_id)
        self.assertEqual(["hello"], FakeClient.sent_text)
        self.assertEqual("", stderr.getvalue())

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

    def test_cli_retry_diagnostics_ignore_root_error_level(self):
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.ERROR)
        self.addCleanup(root.setLevel, old_level)
        outcomes = iter(
            (
                NetworkFailure("temporary"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token"}),
                JsonResponse(200, {"code": 0}),
            )
        )

        def transport(url, headers, payload, timeout):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        code, _, stderr = self.invoke(
            ["send", "--message", "hello"],
            client_factory=lambda config: FeishuClient(
                config, transport=transport, sleep=lambda _: None
            ),
        )
        self.assertEqual(0, code)
        self.assertIn("Feishu retry [network] attempt 1/3", stderr)

    def test_cli_retry_diagnostics_do_not_propagate_to_root_handler(self):
        root = logging.getLogger()
        old_level = root.level
        root_stream = io.StringIO()
        root_handler = logging.StreamHandler(root_stream)
        root.setLevel(logging.WARNING)
        root.addHandler(root_handler)
        self.addCleanup(root.removeHandler, root_handler)
        self.addCleanup(root.setLevel, old_level)
        outcomes = iter(
            (
                NetworkFailure("temporary"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token"}),
                JsonResponse(200, {"code": 0}),
            )
        )

        def transport(url, headers, payload, timeout):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        code, _, stderr = self.invoke(
            ["send", "--message", "hello"],
            client_factory=lambda config: FeishuClient(
                config, transport=transport, sleep=lambda _: None
            ),
        )
        self.assertEqual(0, code)
        self.assertIn("Feishu retry [network] attempt 1/3", stderr)
        self.assertEqual("", root_stream.getvalue())

    def test_cli_restores_logger_state_after_exception(self):
        original_level = LOGGER.level
        original_propagate = LOGGER.propagate
        LOGGER.setLevel(logging.ERROR)
        LOGGER.propagate = True
        self.addCleanup(setattr, LOGGER, "level", original_level)
        self.addCleanup(setattr, LOGGER, "propagate", original_propagate)

        def client_factory(config):
            self.assertEqual(logging.WARNING, LOGGER.level)
            self.assertFalse(LOGGER.propagate)
            raise RuntimeError("test failure")

        with self.assertRaisesRegex(RuntimeError, "test failure"):
            self.invoke(["send", "--message", "hello"], client_factory=client_factory)
        self.assertEqual(logging.ERROR, LOGGER.level)
        self.assertTrue(LOGGER.propagate)

    def test_stdin_send_uses_same_send_flow(self):
        code, _, stderr = self.invoke(
            ["stdin"],
            stdin=io.StringIO('{"flow":"send","message":"hello"}'),
        )
        self.assertEqual(0, code)
        self.assertEqual(["hello"], FakeClient.sent_text)
        self.assertEqual("", stderr)

    def test_stdin_task_auto_sends_same_card(self):
        literal_content = "请选择 A 或 B；不要执行 $(touch /tmp/feishu-shell-marker)"
        payload = {
            "flow": "task-auto",
            "status": "confirm",
            "project": "HETU",
            "conversation": "架构师",
            "content": literal_content,
        }
        code, _, stderr = self.invoke(
            ["stdin"], stdin=io.StringIO(json.dumps(payload))
        )
        self.assertEqual(0, code)
        self.assertEqual(
            "HETU-架构师-待确认",
            FakeClient.sent_cards[0]["header"]["title"]["content"],
        )
        self.assertEqual(
            literal_content,
            FakeClient.sent_cards[0]["elements"][0]["text"]["content"],
        )
        self.assertEqual("", stderr)

    def test_stdin_task_rejects_non_whitelisted_or_invalid_payloads(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("invalid stdin constructed a client")

        for payload in (
            {
                "flow": "task-auto",
                "status": "success",
                "task": "old",
                "summary": "old",
                "repo": "r",
                "branch": "b",
            },
            {
                "flow": "task-auto",
                "status": "success",
                "project": "p",
                "conversation": "c",
                "content": "x",
                "source": "Codex",
            },
            {
                "flow": "task-auto",
                "status": "success",
                "project": "p",
                "conversation": "c",
            },
            {
                "flow": "task-auto",
                "status": "cancel",
                "project": "p",
                "conversation": "c",
                "content": "x",
            },
            {
                "flow": "task-auto",
                "status": "success",
                "project": "p",
                "conversation": "c",
                "content": None,
            },
        ):
            with self.subTest(payload=payload):
                code, _, stderr = self.invoke(
                    ["stdin"],
                    client_factory=ClientMustNotStart,
                    stdin=io.StringIO(json.dumps(payload)),
                )
                self.assertEqual(2, code)
                self.assertEqual("Invalid stdin input\n", stderr)

    def test_stdin_task_auto_disabled_does_not_construct_client(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("disabled auto task constructed a client")

        payload = {
            "flow": "task-auto",
            "status": "success",
            "project": "p",
            "conversation": "c",
            "content": "x",
        }
        code, stdout, stderr = self.invoke(
            ["stdin"],
            environ={"FEISHU_AUTO_NOTIFY": "false"},
            client_factory=ClientMustNotStart,
            stdin=io.StringIO(json.dumps(payload)),
        )
        self.assertEqual(0, code)
        self.assertIn("disabled", stdout)
        self.assertEqual("", stderr)

    def test_invalid_stdin_returns_exit_2_without_client(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("invalid stdin constructed a client")

        code, _, stderr = self.invoke(
            ["stdin"],
            stdin=io.StringIO('{"flow":"send","message":null}'),
            client_factory=ClientMustNotStart,
        )
        self.assertEqual(2, code)
        self.assertIn("Invalid stdin input", stderr)

    def test_parser_invalid_stdin_returns_fixed_diagnostic_without_client(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("invalid stdin constructed a client")

        code, _, stderr = self.invoke(
            ["stdin"],
            stdin=io.StringIO('{"flow":"send","message":" "}'),
            client_factory=ClientMustNotStart,
        )
        self.assertEqual(2, code)
        self.assertEqual("Invalid stdin input\n", stderr)


if __name__ == "__main__":
    unittest.main()
