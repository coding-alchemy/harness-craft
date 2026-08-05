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

    def test_malformed_env_encoding_returns_3_without_leaking_secret(self):
        self.env_file.write_bytes(b"FEISHU_APP_SECRET=top-secret\n\xff")
        code, _, stderr = self.invoke(["send", "--message", "hello"])
        self.assertEqual(3, code)
        self.assertIn("Feishu configuration error", stderr)
        self.assertNotIn("top-secret", stderr)

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
