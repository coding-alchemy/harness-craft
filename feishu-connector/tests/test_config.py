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
