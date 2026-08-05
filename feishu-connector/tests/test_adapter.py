import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feishu_notify_adapter  # noqa: E402


class AdapterTests(unittest.TestCase):
    def test_send_preserves_hostile_message_as_one_argv_value_and_exit_code(self):
        message = '"quoted"\n$(not-a-command) `not-a-command` --leading'
        completed = type("Completed", (), {"returncode": 17})()
        with patch("feishu_notify_adapter.subprocess.run", return_value=completed) as run:
            code = feishu_notify_adapter.main(
                stdin=io.StringIO(json.dumps({"flow": "send", "message": message}))
            )

        self.assertEqual(17, code)
        self.assertEqual(
            [
                sys.executable,
                str(SCRIPTS / "feishu_notify.py"),
                "send",
                "--message=%s" % message,
            ],
            run.call_args.args[0],
        )
        self.assertEqual({"check": False, "shell": False}, run.call_args.kwargs)

    def test_task_auto_preserves_hostile_fields_as_argv_values_and_exit_code(self):
        payload = {
            "flow": "task-auto",
            "status": "failure",
            "task": '"task"\n$(not-a-command)',
            "summary": '`summary` --leading',
            "repo": "repo\n$(not-a-command)",
            "branch": "--branch `not-a-command`",
        }
        completed = type("Completed", (), {"returncode": 5})()
        with patch("feishu_notify_adapter.subprocess.run", return_value=completed) as run:
            code = feishu_notify_adapter.main(stdin=io.StringIO(json.dumps(payload)))

        self.assertEqual(5, code)
        self.assertEqual(
            [
                sys.executable,
                str(SCRIPTS / "feishu_notify.py"),
                "task",
                "--auto",
                "--status=%s" % payload["status"],
                "--task=%s" % payload["task"],
                "--summary=%s" % payload["summary"],
                "--repo=%s" % payload["repo"],
                "--branch=%s" % payload["branch"],
            ],
            run.call_args.args[0],
        )

    def test_invalid_json_or_shape_does_not_invoke_subprocess(self):
        for raw in (
            "not json",
            json.dumps({"flow": "send"}),
            json.dumps({"flow": "other", "message": "hello"}),
            json.dumps({"flow": "send", "message": "x", "extra": "y"}),
            json.dumps({"flow": "task-auto", "status": "invalid", "task": "x", "summary": "x", "repo": "x", "branch": "x"}),
            json.dumps({"flow": "task-auto", "status": "success", "task": "x", "summary": "x", "repo": "x"}),
            json.dumps({"flow": "task-auto", "status": "success", "task": 123, "summary": "x", "repo": "x", "branch": "x"}),
            json.dumps({"flow": "task-auto", "status": "success", "task": "", "summary": "x", "repo": "x", "branch": "x"}),
            json.dumps({"flow": "send", "message": "   "}),
        ):
            with self.subTest(raw=raw):
                with patch("feishu_notify_adapter.subprocess.run") as run:
                    self.assertEqual(
                        2,
                        feishu_notify_adapter.main(
                            stdin=io.StringIO(raw), stderr=io.StringIO()
                        ),
                    )
                run.assert_not_called()

    def test_null_byte_in_message_returns_exit_2_at_validation(self):
        with patch("feishu_notify_adapter.subprocess.run") as run:
            code = feishu_notify_adapter.main(
                stdin=io.StringIO(json.dumps({"flow": "send", "message": "bad\u0000char"})),
                stderr=io.StringIO(),
            )
        self.assertEqual(2, code)
        run.assert_not_called()

    def test_large_message_returns_exit_2_on_os_error(self):
        with patch("feishu_notify_adapter.subprocess.run") as run:
            run.side_effect = OSError(7, "Argument list too long")
            code = feishu_notify_adapter.main(
                stdin=io.StringIO(json.dumps({"flow": "send", "message": "x" * 10**6})),
                stderr=io.StringIO(),
            )
        self.assertEqual(2, code)

    def test_lone_surrogate_in_message_returns_exit_2_via_real_subprocess(self):
        code = feishu_notify_adapter.main(
            stdin=io.StringIO(json.dumps({"flow": "send", "message": "\ud800"})),
            stderr=io.StringIO(),
        )
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
