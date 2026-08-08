import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from feishu_config import (  # noqa: E402
    ConfigPaths,
    ConfigError,
    auto_notify_enabled,
    build_config_paths,
    format_source_diagnostics,
    legacy_migration_message,
    load_config,
    load_json_fields,
    missing_required_fields,
    parse_bool,
    resolve_project_root,
    resolve_settings,
    validate_global_secret_permissions,
)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write_json(self, name, payload, mode=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        if mode is not None:
            path.chmod(mode)
        return path

    def make_symlink_or_skip(self, link, target):
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError) as exc:
            self.skipTest("symbolic links are unavailable: %s" % exc)

    def test_loads_known_leaf_fields_and_missing_file_is_empty(self):
        path = self.write_json(
            "global.json",
            {
                "app": {"appId": "cli_global", "appSecret": "secret"},
                "recipient": {"openId": "ou_global"},
                "notification": {"autoNotify": False},
            },
            mode=0o600,
        )
        self.assertEqual(
            {
                "app.appId": "cli_global",
                "app.appSecret": "secret",
                "recipient.openId": "ou_global",
                "notification.autoNotify": False,
            },
            load_json_fields(path, "global", allow_app_secret=True),
        )
        self.assertEqual(
            {},
            load_json_fields(
                self.root / "missing.json", "global", allow_app_secret=True
            ),
        )

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics required")
    def test_rejects_global_secret_file_with_group_or_other_read_write_bits(self):
        path = self.write_json(
            "wide/config.json", {"app": {"appSecret": "never-print"}}, mode=0o644
        )
        with self.assertRaises(ConfigError) as raised:
            load_json_fields(path, "global", allow_app_secret=True)
        self.assertIn("chmod 600", str(raised.exception))
        self.assertNotIn("never-print", str(raised.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics required")
    def test_accepts_global_secret_file_mode_600(self):
        path = self.write_json(
            "safe/config.json", {"app": {"appSecret": "safe-secret"}}, mode=0o600
        )
        self.assertEqual(
            "safe-secret",
            load_json_fields(path, "global", allow_app_secret=True)[
                "app.appSecret"
            ],
        )

    def test_source_diagnostics_show_sources_and_no_values(self):
        global_file = self.write_json(
            "diagnostic-global.json",
            {
                "app": {"appId": "cli_global", "appSecret": "hidden-secret"},
                "recipient": {"openId": "ou_global_hidden"},
            },
            mode=0o600,
        )
        project_file = self.write_json(
            "diagnostic-project.json",
            {
                "app": {"appId": "cli_project"},
                "notification": {"autoNotify": True},
            },
        )
        resolved = load_config(
            ConfigPaths(global_file, project_file, self.root / ".env"),
            {"FEISHU_RECEIVE_OPEN_ID": "ou_environment_hidden"},
        )
        output = format_source_diagnostics(resolved)
        self.assertEqual(
            "app.appId: project\n"
            "app.appSecret: global (redacted)\n"
            "recipient.openId: environment (redacted)\n"
            "notification.autoNotify: project",
            output,
        )
        for hidden in ("hidden-secret", "ou_global_hidden", "ou_environment_hidden"):
            self.assertNotIn(hidden, output)

    def test_legacy_env_detection_never_reads_contents(self):
        legacy = self.root / ".env"
        legacy.write_text("FEISHU_APP_SECRET=must-not-be-read\n", encoding="utf-8")
        with mock.patch.object(
            Path, "read_text", side_effect=AssertionError("legacy .env was read")
        ):
            message = legacy_migration_message(legacy)
        self.assertIn("not read", message)
        self.assertNotIn("must-not-be-read", message)
        self.assertIsNone(legacy_migration_message(self.root / "absent.env"))

    def test_rejects_unknown_null_and_wrong_type_without_echoing_values(self):
        cases = (
            ({"ou_leaked_open_id_1234": {}}, "unknown top-level configuration field"),
            ({"app": {"ou_leaked_open_id_1234": "cli_typo"}}, "unknown field in app configuration"),
            ({"recipient": {"bad\nfield": "ou_value"}}, "unknown field in recipient configuration"),
            ({"recipient": {"openId": None}}, "must not be null"),
            ({"notification": {"autoNotify": "true"}}, "must be a boolean"),
            ({"app": []}, "app must be an object"),
        )
        for index, (payload, message) in enumerate(cases):
            with self.subTest(payload=payload):
                path = self.write_json("invalid-%d.json" % index, payload)
                with self.assertRaisesRegex(ConfigError, message) as raised:
                    load_json_fields(path, "global", allow_app_secret=True)
                self.assertTrue(str(raised.exception).isascii())
                self.assertNotIn("ou_leaked_open_id_1234", str(raised.exception))

    def test_rejects_project_app_secret_even_when_null_empty_or_fake(self):
        for index, value in enumerate((None, "", "fake-secret")):
            with self.subTest(value=value):
                path = self.write_json(
                    "project-%d.json" % index,
                    {"app": {"appSecret": value}},
                )
                with self.assertRaisesRegex(
                    ConfigError, "project configuration must not contain app.appSecret"
                ):
                    load_json_fields(path, "project", allow_app_secret=False)

    def test_rejects_duplicate_json_keys_at_root_and_nested_levels(self):
        cases = (
            ('{"app":{"appSecret":"secret"},"app":{"appId":"cli"}}', "project"),
            ('{"recipient":{"openId":"one","openId":"two"}}', "global"),
        )
        for index, (raw, source) in enumerate(cases):
            path = self.root / ("duplicate-%d.json" % index)
            path.write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ConfigError, "duplicate JSON key"):
                    load_json_fields(
                        path, source, allow_app_secret=(source == "global")
                    )

    def test_rejects_unpaired_surrogates_in_json_keys_values_and_environment(self):
        for name, payload in (
            ("surrogate-value.json", {"app": {"appId": "\ud800"}}),
            ("surrogate-key.json", {"\ud800": {}}),
        ):
            path = self.write_json(name, payload)
            with self.subTest(name=name):
                with self.assertRaises(ConfigError) as raised:
                    load_json_fields(path, "global", allow_app_secret=True)
                self.assertTrue(str(raised.exception).isascii())

        global_file = self.write_json(
            "surrogate-global.json",
            {
                "app": {"appId": "cli", "appSecret": "secret"},
                "recipient": {"openId": "ou_valid"},
            },
            mode=0o600,
        )
        paths = ConfigPaths(global_file, self.root / "missing.json", self.root / ".env")
        with self.assertRaises(ConfigError) as raised:
            load_config(paths, {"FEISHU_RECEIVE_OPEN_ID": "\ud800"})
        self.assertTrue(str(raised.exception).isascii())

    def test_rejects_malformed_or_unreadable_json_without_file_contents(self):
        path = self.root / "broken.json"
        path.write_text('{"app":{"appSecret":"never-print"}', encoding="utf-8")
        with self.assertRaises(ConfigError) as raised:
            load_json_fields(path, "global", allow_app_secret=True)
        self.assertNotIn("never-print", str(raised.exception))

    def test_environment_boolean_parser_remains_strict(self):
        self.assertTrue(parse_bool("TRUE", "FEISHU_AUTO_NOTIFY"))
        self.assertFalse(parse_bool("false", "FEISHU_AUTO_NOTIFY"))
        with self.assertRaisesRegex(ConfigError, "true or false"):
            parse_bool("yes", "FEISHU_AUTO_NOTIFY")

    def test_project_root_precedence_is_explicit_then_git_then_cwd(self):
        cwd = self.root / "work" / "nested"
        explicit = self.root / "explicit"
        git_root = self.root / "git-root"
        cwd.mkdir(parents=True)
        explicit.mkdir()
        git_root.mkdir()

        def git_runner(argv, **kwargs):
            self.assertEqual(["git", "-C", str(cwd.resolve()), "rev-parse", "--show-toplevel"], argv)
            return subprocess.CompletedProcess(argv, 0, str(git_root) + "\n", "")

        self.assertEqual(
            explicit.resolve(),
            resolve_project_root(explicit, cwd, git_runner=git_runner),
        )
        self.assertEqual(
            git_root.resolve(),
            resolve_project_root(None, cwd, git_runner=git_runner),
        )

        def no_git(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 128, "", "")

        self.assertEqual(
            cwd.resolve(),
            resolve_project_root(None, cwd, git_runner=no_git),
        )

    def test_builds_exact_global_project_and_legacy_paths(self):
        project = self.root / "project"
        connector = self.root / "connector"
        home = self.root / "home"
        project.mkdir()
        paths = build_config_paths(
            explicit_project_root=project,
            cwd=self.root,
            home=home,
            connector_root=connector,
        )
        self.assertEqual(
            home.resolve() / ".config" / "feishu-connector" / "config.json",
            paths.global_file,
        )
        self.assertEqual(
            project.resolve() / ".config" / "feishu-connector" / "config.json",
            paths.project_file,
        )
        self.assertEqual(connector / ".env", paths.legacy_env_file)

    def test_home_project_path_collision_uses_the_global_layer_once(self):
        home = self.root / "home"
        config_file = self.write_json(
            "home/.config/feishu-connector/config.json",
            {
                "app": {"appId": "cli", "appSecret": "secret"},
                "recipient": {"openId": "ou_global"},
            },
            mode=0o600,
        )
        paths = build_config_paths(
            explicit_project_root=home,
            cwd=self.root,
            home=home,
            connector_root=self.root / "connector",
        )
        self.assertEqual(config_file.resolve(), paths.global_file)
        self.assertEqual(paths.global_file, paths.project_file)
        resolution = load_config(paths, {})
        self.assertEqual("global", resolution.sources["app.appSecret"])

    def test_same_home_and_project_directory_uses_global_file_once(self):
        home = self.root / "home"
        global_file = self.write_json(
            "home/.config/feishu-connector/config.json",
            {
                "app": {"appId": "cli", "appSecret": "secret"},
                "recipient": {"openId": "ou_global"},
            },
            mode=0o600,
        )
        project_root = self.root / "project-alias"
        project_root.mkdir()
        with mock.patch.object(Path, "samefile", return_value=True):
            paths = build_config_paths(
                explicit_project_root=project_root,
                cwd=self.root,
                home=home,
                connector_root=self.root / "connector",
            )
        self.assertEqual(global_file.resolve(), paths.global_file)
        self.assertEqual(paths.global_file, paths.project_file)
        self.assertEqual("global", load_config(paths, {}).sources["app.appSecret"])

    def test_unresolvable_config_paths_raise_config_error(self):
        paths = ConfigPaths(
            self.root / "missing.json", self.root / "project.json", self.root / ".env"
        )
        with mock.patch.object(Path, "resolve", side_effect=RuntimeError("loop")):
            with self.assertRaises(ConfigError) as raised:
                resolve_settings(paths, {})
            self.assertTrue(str(raised.exception).isascii())

            with self.assertRaises(ConfigError) as raised:
                build_config_paths(
                    explicit_project_root=self.root,
                    cwd=self.root,
                    home=self.root / "home",
                    connector_root=self.root / "connector",
                )
            self.assertTrue(str(raised.exception).isascii())

    def test_rejects_invalid_paths_and_git_root_as_config_errors(self):
        with self.assertRaises(ConfigError) as raised:
            resolve_project_root("\0", self.root)
        self.assertTrue(str(raised.exception).isascii())

        def git_runner(argv, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\\xff", 0, 1, "invalid")

        with self.assertRaises(ConfigError) as raised:
            resolve_project_root(None, self.root, git_runner=git_runner)
        self.assertTrue(str(raised.exception).isascii())

    def test_rejects_json_limit_failures_as_config_errors(self):
        path = self.root / "limit.json"
        path.write_text("{\"app\":{\"appId\":%s}}" % ("9" * 5000), encoding="utf-8")
        with self.assertRaises(ConfigError) as raised:
            load_json_fields(path, "global", allow_app_secret=True)
        self.assertTrue(str(raised.exception).isascii())

        with mock.patch("feishu_config.json.loads", side_effect=RecursionError):
            with self.assertRaises(ConfigError) as raised:
                load_json_fields(path, "global", allow_app_secret=True)
        self.assertTrue(str(raised.exception).isascii())

    def test_merges_environment_over_project_over_global_by_leaf(self):
        global_file = self.write_json(
            "global/config.json",
            {
                "app": {"appId": "cli_global", "appSecret": "global-secret"},
                "recipient": {"openId": "ou_global"},
                "notification": {"autoNotify": False},
            },
            mode=0o600,
        )
        project_file = self.write_json(
            "project/config.json",
            {
                "app": {"appId": "cli_project"},
                "recipient": {"openId": "ou_project"},
            },
        )
        paths = ConfigPaths(global_file, project_file, self.root / ".env")
        resolved = load_config(
            paths,
            {
                "FEISHU_RECEIVE_OPEN_ID": "ou_environment",
                "FEISHU_AUTO_NOTIFY": "true",
            },
        )
        self.assertEqual("cli_project", resolved.config.app_id)
        self.assertEqual("global-secret", resolved.config.app_secret)
        self.assertEqual("ou_environment", resolved.config.receive_open_id)
        self.assertTrue(resolved.config.auto_notify)
        self.assertEqual(
            {
                "app.appId": "project",
                "app.appSecret": "global",
                "recipient.openId": "environment",
                "notification.autoNotify": "environment",
            },
            dict(resolved.sources),
        )

    def test_symlinked_global_file_does_not_bypass_project_secret_ban(self):
        project_file = self.write_json(
            "project/config.json",
            {"app": {"appSecret": "forbidden-project-secret"}},
            mode=0o600,
        )
        global_link = self.root / "global-link.json"
        self.make_symlink_or_skip(global_link, project_file)
        paths = ConfigPaths(global_link, project_file, self.root / ".env")
        with self.assertRaisesRegex(
            ConfigError, "project configuration must not contain app.appSecret"
        ):
            resolve_settings(paths, {})

    def test_project_single_field_inherits_others_and_environment_can_complete(self):
        project_file = self.write_json(
            "project-only/config.json",
            {"recipient": {"openId": "ou_project"}},
        )
        paths = ConfigPaths(
            self.root / "absent-global.json",
            project_file,
            self.root / ".env",
        )
        resolved = load_config(
            paths,
            {
                "FEISHU_APP_ID": "cli_environment",
                "FEISHU_APP_SECRET": "environment-secret",
            },
        )
        self.assertEqual("ou_project", resolved.config.receive_open_id)
        self.assertFalse(resolved.config.auto_notify)
        self.assertEqual("default", resolved.sources["notification.autoNotify"])

    def test_present_environment_field_is_validated_instead_of_inheriting(self):
        global_file = self.write_json(
            "valid-global.json",
            {
                "app": {"appId": "cli_global", "appSecret": "global-secret"},
                "recipient": {"openId": "ou_global"},
            },
            mode=0o600,
        )
        paths = ConfigPaths(global_file, self.root / "missing.json", self.root / ".env")
        with self.assertRaisesRegex(ConfigError, "FEISHU_APP_ID must not be empty"):
            load_config(paths, {"FEISHU_APP_ID": ""})

    def test_auto_gate_validates_sources_but_does_not_require_credentials(self):
        project_file = self.write_json(
            "auto/config.json", {"notification": {"autoNotify": True}}
        )
        paths = ConfigPaths(
            self.root / "missing-global.json", project_file, self.root / ".env"
        )
        self.assertTrue(auto_notify_enabled(paths, {}))
        settings = resolve_settings(paths, {})
        self.assertEqual(
            ("app.appId", "app.appSecret", "recipient.openId"),
            missing_required_fields(settings),
        )


if __name__ == "__main__":
    unittest.main()
