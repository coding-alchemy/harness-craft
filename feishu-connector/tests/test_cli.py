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

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from feishu_notify import (  # noqa: E402
    ConnectorError,
    FeishuClient,
    JsonResponse,
    LOGGER,
    NetworkFailure,
    main,
    render_task_message,
)
from feishu_config import ConfigPaths  # noqa: E402


class FakeClient:
    sent = []
    configs = []
    error = None

    def __init__(self, config):
        self.config = config
        self.configs.append(config)

    def send_text(self, message):
        if self.error is not None:
            raise self.error
        self.sent.append(message)


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeClient.sent = []
        FakeClient.configs = []
        FakeClient.error = None
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.global_file = self.root / "global.json"
        self.project_file = self.root / "project.json"
        self.legacy_env_file = self.root / ".env"
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
            self.global_file, self.project_file, self.legacy_env_file
        )

    def invoke(self, argv, environ=None, client_factory=FakeClient):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            argv=argv,
            environ={} if environ is None else environ,
            config_paths=self.config_paths,
            client_factory=client_factory,
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

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

    def test_send_sends_exact_plain_text(self):
        code, stdout, stderr = self.invoke(["send", "--message", "hello 飞书"])
        self.assertEqual(0, code)
        self.assertEqual(["hello 飞书"], FakeClient.sent)
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
        self.global_file.write_text(
            json.dumps({"notification": {"autoNotify": False}}), encoding="utf-8"
        )
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

    def test_auto_environment_false_overrides_json_true_without_client(self):
        class ClientMustNotStart:
            def __init__(self, config):
                raise AssertionError("disabled auto task constructed a client")

        code, stdout, stderr = self.invoke(
            [
                "task", "--auto",
                "--status", "success",
                "--task", "task",
                "--summary", "summary",
                "--repo", "repo",
                "--branch", "branch",
            ],
            environ={"FEISHU_AUTO_NOTIFY": "false"},
            client_factory=ClientMustNotStart,
        )
        self.assertEqual(0, code)
        self.assertIn("disabled", stdout)
        self.assertEqual("", stderr)

    def test_auto_task_uses_one_configuration_snapshot(self):
        original_resolve = __import__("feishu_notify").resolve_settings

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

        with mock.patch("feishu_notify.resolve_settings", side_effect=change_after_resolution) as resolver:
            code, _, stderr = self.invoke(
                [
                    "task", "--auto",
                    "--status", "success",
                    "--task", "task",
                    "--summary", "summary",
                    "--repo", "repo",
                    "--branch", "branch",
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
        self.assertEqual(["explicit"], FakeClient.sent)

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
            self.root / "global.json", self.project_file, self.legacy_env_file
        )

        class NetworkMustNotStart:
            def __init__(self, config):
                raise AssertionError("client started before path validation")

        with mock.patch("feishu_config.Path.resolve", side_effect=RuntimeError("loop")):
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

    def test_opencode_source_remains_supported_by_same_task_command(self):
        code, _, stderr = self.invoke(
            [
                "task",
                "--status", "success",
                "--task", "task",
                "--summary", "summary",
                "--repo", "repo",
                "--branch", "branch",
                "--source", "OpenCode",
            ]
        )
        self.assertEqual(0, code)
        self.assertTrue(FakeClient.sent[-1].startswith("[OpenCode] SUCCESS\n"))
        self.assertEqual("", stderr)

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

    def test_legacy_env_yields_migration_guidance_without_being_read(self):
        self.global_file.unlink()
        self.legacy_env_file.write_text(
            "FEISHU_APP_SECRET=must-not-appear\n", encoding="utf-8"
        )
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(3, code)
        self.assertIn("legacy .env was not read", stderr)
        self.assertNotIn("must-not-appear", stderr)

    def test_auto_disabled_with_incomplete_phase_two_config_is_noop_with_hint(self):
        self.global_file.write_text(
            json.dumps({"notification": {"autoNotify": False}}), encoding="utf-8"
        )
        self.legacy_env_file.write_text("opaque legacy contents", encoding="utf-8")
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
        self.assertIn("disabled", stdout)
        self.assertIn("legacy .env was not read", stderr)
        self.assertEqual([], FakeClient.sent)

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

    def test_render_rejects_empty_task_fields(self):
        with self.assertRaisesRegex(ValueError, "summary"):
            render_task_message("Codex", "success", "task", "", "repo", "branch")


if __name__ == "__main__":
    unittest.main()
