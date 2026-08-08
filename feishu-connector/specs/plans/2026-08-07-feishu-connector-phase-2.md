# Feishu Connector Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Phase 1 `.env` loading with secure, source-aware JSON configuration that merges process environment, project JSON, and global JSON by field, while preserving the existing Feishu messaging CLI and its future OpenCode-compatible boundary.

**Architecture:** Move configuration discovery, JSON validation, source tracking, secret policy, and migration detection into a focused `feishu_config.py` module. Keep authentication, HTTP, retry, message rendering, exit codes, and the `send`/`task` contracts in `feishu_notify.py`; add only a read-only `config` diagnostic command and a global `--project-root` option. The stdin adapter and Feishu client remain protocol-compatible and continue to call the same CLI without duplicating configuration or messaging logic.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `os`, `pathlib`, `stat`, `subprocess`, `typing`, `unittest`, `unittest.mock`), Markdown, Git.

## Global Constraints

- Implement only Section 14, “第二期：多级 JSON 配置,” from `feishu-connector/specs/feishu-connector.md`; do not add an OpenCode Skill or adapter in this phase.
- Configuration priority is fixed, field by field: process environment > project JSON > global JSON.
- Resolve the project root in this order: explicit `--project-root`, current Git repository top level, current working directory.
- Read the global fallback from `~/.config/feishu-connector/config.json` and the project override from `<project-root>/.config/feishu-connector/config.json`.
- Preserve the environment names `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_RECEIVE_OPEN_ID`, and `FEISHU_AUTO_NOTIFY` as the highest-priority compatibility layer.
- Phase 2 must never read `feishu-connector/.env`; its presence is used only to decide whether to print migration guidance.
- Reject explicit JSON `null`, unknown objects or fields, invalid field types, and project `app.appSecret` before any network request.
- Permit `appSecret` only in the process environment or global JSON. On POSIX, reject a global secret file whose mode grants group or other read/write permission and recommend `chmod 600`.
- Never print App Secret, access tokens, or complete Open IDs. Configuration diagnostics show sources only and mark Secret/Open ID as redacted.
- Keep `send`, `task`, `task --auto`, `--source Codex|OpenCode`, message rendering, Feishu client behavior, retry policy, and exit codes backward-compatible.
- Use Python 3 standard library only. All default tests remain offline and must not depend on a Git repository, the user's home configuration, or real credentials.
- Follow test-driven development for every implementation task: add a focused failing test, confirm the expected failure, add the minimum implementation, rerun the focused test, then run the affected regression tests.
- Make one focused commit at the end of Tasks 1–5. Task 6 is a read-only final verification gate and creates no commit.

## File Map

| Path | Responsibility |
|---|---|
| `feishu-connector/scripts/feishu_config.py` | JSON schema validation, project-root and path discovery, source-aware field merge, required-field materialization, secret permission policy, diagnostics, and legacy `.env` migration detection |
| `feishu-connector/scripts/feishu_notify.py` | Existing Feishu client and message CLI; imports Phase 2 configuration APIs, adds `--project-root` and read-only `config` diagnostics, and no longer reads `.env` |
| `feishu-connector/scripts/feishu_notify_adapter.py` | Unchanged safe stdin-to-argv adapter; regression-tested to prove the stable CLI boundary remains usable by Codex and future OpenCode adapters |
| `feishu-connector/tests/test_config.py` | Phase 2 JSON schema, discovery, merge priority, source tracking, secret policy, permissions, and migration tests; replaces Phase 1 `.env` parser tests |
| `feishu-connector/tests/test_cli.py` | CLI integration, config diagnostics, project-root override, pre-network failures, automatic-notification gate, migration warning, and existing send/task behavior |
| `feishu-connector/tests/test_client.py` | Unchanged Feishu HTTP, retry, and payload tests; verifies configuration refactoring does not alter the client |
| `feishu-connector/tests/test_adapter.py` | Unchanged safe adapter tests; verifies `send` and `task --auto` remain stable |
| `feishu-connector/tests/test_skill_contract.py` | Documentation and Skill contract assertions updated from Phase 1 `.env` wording to Phase 2 JSON/source behavior |
| `feishu-connector/README.md` | Authoritative setup, configuration precedence, security, migration, diagnostic command, testing, and manual acceptance documentation |
| `feishu-connector/docs/USAGE.md` | Concise Phase 2 setup and daily-use guide |
| `feishu-connector/skills/feishu-notify/SKILL.md` | Thin Codex calling policy; documents that the CLI resolves Phase 2 configuration and that the Skill still never reads secrets |
| `feishu-connector/.env.example` | Delete because Phase 2 does not read `.env`; retain the `.gitignore` rule for legacy real `.env` files |

## Stable Interfaces

`feishu-connector/scripts/feishu_config.py` will expose these exact names:

```python
class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    app_id: str
    app_secret: str
    receive_open_id: str
    auto_notify: bool


@dataclass(frozen=True)
class ConfigPaths:
    global_file: Path
    project_file: Path
    legacy_env_file: Path


@dataclass(frozen=True)
class ResolvedSettings:
    values: Mapping[str, object]
    sources: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedConfig:
    config: Config
    sources: Mapping[str, str]
```

The exact callable contracts are:

- `parse_bool(value, key) -> bool`
- `load_json_fields(path, source, allow_app_secret) -> Mapping[str, object]`
- `resolve_project_root(explicit_project_root, cwd, git_runner=subprocess.run) -> Path`
- `build_config_paths(explicit_project_root=None, cwd=None, home=None, git_runner=subprocess.run, connector_root=None) -> ConfigPaths`
- `resolve_settings(paths, environ) -> ResolvedSettings`
- `missing_required_fields(settings) -> Sequence[str]`
- `load_config(paths, environ) -> ResolvedConfig`
- `auto_notify_enabled(paths, environ) -> bool`
- `validate_global_secret_permissions(path) -> None`
- `format_source_diagnostics(resolution) -> str`
- `legacy_migration_message(legacy_env_file) -> Optional[str]`

`feishu_notify.py` re-exports imported `Config`, `ConfigError`, and `parse_bool` so existing internal imports in client tests and external lightweight callers do not break. Its public CLI remains:

```text
python3 feishu-connector/scripts/feishu_notify.py [--project-root PATH] send --message TEXT
python3 feishu-connector/scripts/feishu_notify.py [--project-root PATH] task [--auto] --status {success,failure} --task TEXT --summary TEXT --repo TEXT --branch TEXT [--source {Codex,OpenCode}]
python3 feishu-connector/scripts/feishu_notify.py [--project-root PATH] config
```

---

### Task 1: Strict JSON parser and field schema

**Files:**
- Create: `feishu-connector/scripts/feishu_config.py`
- Replace: `feishu-connector/tests/test_config.py`

**Interfaces:**
- Produces: `ConfigError`, `Config`, `parse_bool(value, key)`, and `load_json_fields(path, source, allow_app_secret)`.
- `load_json_fields` returns a flat mapping keyed by `app.appId`, `app.appSecret`, `recipient.openId`, and `notification.autoNotify`; absent files return `{}`.
- Later tasks consume only the flattened fields and never traverse unvalidated JSON themselves.

- [ ] **Step 1: Replace Phase 1 parser tests with failing JSON schema tests**

Create the imports and helpers at the top of `feishu-connector/tests/test_config.py`:

```python
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
    ConfigError,
    load_json_fields,
    parse_bool,
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
```

Add these tests to `ConfigTests`:

```python
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

    def test_rejects_unknown_null_and_wrong_type_without_echoing_values(self):
        cases = (
            ({"appp": {}}, "unknown field: appp"),
            ({"app": {"appID": "cli_typo"}}, "unknown field: app.appID"),
            ({"recipient": {"openId": None}}, "must not be null"),
            ({"notification": {"autoNotify": "true"}}, "must be a boolean"),
            ({"app": []}, "app must be an object"),
        )
        for index, (payload, message) in enumerate(cases):
            with self.subTest(payload=payload):
                path = self.write_json("invalid-%d.json" % index, payload)
                with self.assertRaisesRegex(ConfigError, message):
                    load_json_fields(path, "global", allow_app_secret=True)

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
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'feishu_config'`.

- [ ] **Step 3: Implement the schema parser**

Create `feishu-connector/scripts/feishu_config.py` with this initial content:

```python
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


FIELD_TYPES = {
    "app": {"appId": str, "appSecret": str},
    "recipient": {"openId": str},
    "notification": {"autoNotify": bool},
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    app_id: str
    app_secret: str
    receive_open_id: str
    auto_notify: bool


def parse_bool(value, key):
    if not isinstance(value, str):
        raise ConfigError("%s must be true or false" % key)
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigError("%s must be true or false" % key)


def _read_json_object(path, source):
    path = Path(path)
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError("unable to read valid %s JSON configuration" % source) from exc
    if not isinstance(payload, dict):
        raise ConfigError("%s configuration root must be an object" % source)
    return payload


def load_json_fields(path, source, allow_app_secret):
    payload = _read_json_object(path, source)
    if payload is None:
        return {}
    values = {}
    for group, group_value in payload.items():
        if group not in FIELD_TYPES:
            raise ConfigError("unknown field: %s" % group)
        if not isinstance(group_value, dict):
            raise ConfigError("%s must be an object" % group)
        for leaf, value in group_value.items():
            dotted = "%s.%s" % (group, leaf)
            if leaf not in FIELD_TYPES[group]:
                raise ConfigError("unknown field: %s" % dotted)
            if dotted == "app.appSecret" and not allow_app_secret:
                raise ConfigError(
                    "project configuration must not contain app.appSecret"
                )
            if value is None:
                raise ConfigError("%s must not be null" % dotted)
            expected_type = FIELD_TYPES[group][leaf]
            if not isinstance(value, expected_type):
                expected_name = "a boolean" if expected_type is bool else "a string"
                raise ConfigError("%s must be %s" % (dotted, expected_name))
            if expected_type is str:
                value = value.strip()
                if not value:
                    raise ConfigError("%s must not be empty" % dotted)
            values[dotted] = value
    return values
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: all JSON parser tests PASS; no test performs network I/O.

- [ ] **Step 5: Commit the parser**

```bash
git add feishu-connector/scripts/feishu_config.py feishu-connector/tests/test_config.py
git commit -m "feat: add strict Feishu JSON configuration parser"
```

---

### Task 2: Project-root discovery and field-by-field source merge

**Files:**
- Modify: `feishu-connector/scripts/feishu_config.py`
- Modify: `feishu-connector/tests/test_config.py`

**Interfaces:**
- Consumes: `Config`, `ConfigError`, `load_json_fields`, and `parse_bool` from Task 1.
- Produces: `ConfigPaths`, `ResolvedSettings`, `ResolvedConfig`, `resolve_project_root`, `build_config_paths`, `resolve_settings`, `missing_required_fields`, `load_config`, and `auto_notify_enabled` with the signatures in “Stable Interfaces.”
- `ResolvedSettings.values` uses dotted field names and always contains `notification.autoNotify`; when no source supplies it, the value is `False` and source is `default`.
- `load_config` requires `app.appId`, `app.appSecret`, and `recipient.openId`, then returns a `ResolvedConfig` whose `config` can be passed directly to `FeishuClient`.

- [ ] **Step 1: Add failing discovery and merge tests**

Extend the import list in `test_config.py` with:

```python
    ConfigPaths,
    auto_notify_enabled,
    build_config_paths,
    load_config,
    missing_required_fields,
    resolve_project_root,
    resolve_settings,
```

Add these tests to `ConfigTests`:

```python
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
            home / ".config" / "feishu-connector" / "config.json",
            paths.global_file,
        )
        self.assertEqual(
            project / ".config" / "feishu-connector" / "config.json",
            paths.project_file,
        )
        self.assertEqual(connector / ".env", paths.legacy_env_file)

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
```

- [ ] **Step 2: Run the focused tests and confirm missing-symbol failures**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: FAIL during import because `ConfigPaths` and the merge/discovery functions do not exist yet.

- [ ] **Step 3: Implement discovery, source tracking, and materialization**

Add these imports to `feishu_config.py`:

```python
import subprocess
```

Add these constants and dataclasses after `Config`:

```python
ENVIRONMENT_FIELDS = {
    "FEISHU_APP_ID": "app.appId",
    "FEISHU_APP_SECRET": "app.appSecret",
    "FEISHU_RECEIVE_OPEN_ID": "recipient.openId",
    "FEISHU_AUTO_NOTIFY": "notification.autoNotify",
}
REQUIRED_FIELDS = ("app.appId", "app.appSecret", "recipient.openId")


@dataclass(frozen=True)
class ConfigPaths:
    global_file: Path
    project_file: Path
    legacy_env_file: Path


@dataclass(frozen=True)
class ResolvedSettings:
    values: Mapping[str, object]
    sources: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedConfig:
    config: Config
    sources: Mapping[str, str]
```

Add these exact functions after `load_json_fields`:

```python
def resolve_project_root(explicit_project_root, cwd, git_runner=subprocess.run):
    cwd = Path(cwd).resolve()
    if explicit_project_root is not None:
        root = Path(explicit_project_root).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError("--project-root must name an existing directory")
        return root
    argv = ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]
    try:
        result = git_runner(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return cwd
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return cwd


def build_config_paths(
    explicit_project_root=None,
    cwd=None,
    home=None,
    git_runner=subprocess.run,
    connector_root=None,
):
    cwd = Path.cwd() if cwd is None else Path(cwd)
    home = Path.home() if home is None else Path(home)
    connector_root = (
        Path(__file__).resolve().parents[1]
        if connector_root is None
        else Path(connector_root)
    )
    project_root = resolve_project_root(
        explicit_project_root, cwd, git_runner=git_runner
    )
    return ConfigPaths(
        global_file=home / ".config" / "feishu-connector" / "config.json",
        project_file=(
            project_root / ".config" / "feishu-connector" / "config.json"
        ),
        legacy_env_file=connector_root / ".env",
    )


def _environment_value(environment_name, dotted, value):
    if dotted == "notification.autoNotify":
        return parse_bool(value, environment_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must not be empty" % environment_name)
    return value.strip()


def resolve_settings(paths, environ):
    values = {}
    sources = {}
    layers = (
        ("global", load_json_fields(paths.global_file, "global", True)),
        ("project", load_json_fields(paths.project_file, "project", False)),
    )
    for source, fields in layers:
        for dotted, value in fields.items():
            values[dotted] = value
            sources[dotted] = source
    for environment_name, dotted in ENVIRONMENT_FIELDS.items():
        if environment_name in environ:
            values[dotted] = _environment_value(
                environment_name, dotted, environ[environment_name]
            )
            sources[dotted] = "environment"
    if "notification.autoNotify" not in values:
        values["notification.autoNotify"] = False
        sources["notification.autoNotify"] = "default"
    return ResolvedSettings(values=values, sources=sources)


def missing_required_fields(settings):
    return tuple(field for field in REQUIRED_FIELDS if field not in settings.values)


def load_config(paths, environ):
    settings = resolve_settings(paths, environ)
    missing = missing_required_fields(settings)
    if missing:
        raise ConfigError("missing required configuration: %s" % ", ".join(missing))
    config = Config(
        app_id=settings.values["app.appId"],
        app_secret=settings.values["app.appSecret"],
        receive_open_id=settings.values["recipient.openId"],
        auto_notify=settings.values["notification.autoNotify"],
    )
    return ResolvedConfig(config=config, sources=settings.sources)


def auto_notify_enabled(paths, environ):
    return bool(resolve_settings(paths, environ).values["notification.autoNotify"])
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: all discovery and merge tests PASS, including global-missing/environment-plus-project completion.

- [ ] **Step 5: Commit discovery and merging**

```bash
git add feishu-connector/scripts/feishu_config.py feishu-connector/tests/test_config.py
git commit -m "feat: merge Feishu configuration by source"
```

---

### Task 3: Global secret permissions, safe diagnostics, and `.env` migration detection

**Files:**
- Modify: `feishu-connector/scripts/feishu_config.py`
- Modify: `feishu-connector/tests/test_config.py`

**Interfaces:**
- Consumes: `ConfigPaths`, `ResolvedConfig`, and `resolve_settings` from Task 2.
- Produces: `validate_global_secret_permissions(path)`, `format_source_diagnostics(resolution)`, and `legacy_migration_message(legacy_env_file)`.
- `legacy_migration_message` checks file metadata only. It must not call `read_text`, `open`, or any `.env` parser.
- `format_source_diagnostics` emits field source labels only; it never emits resolved field values.

- [ ] **Step 1: Add failing security and diagnostic tests**

Extend the `feishu_config` import list in `test_config.py` with:

```python
    format_source_diagnostics,
    legacy_migration_message,
    validate_global_secret_permissions,
```

Add these tests:

```python
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
```

- [ ] **Step 2: Run the tests and verify security/diagnostic failures**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: FAIL because mode `0644` is currently accepted and the diagnostic/migration functions are not defined.

- [ ] **Step 3: Implement permission enforcement and safe output helpers**

Add these imports to `feishu_config.py`:

```python
import os
import stat
```

Add these constants after `REQUIRED_FIELDS`:

```python
DIAGNOSTIC_FIELDS = (
    "app.appId",
    "app.appSecret",
    "recipient.openId",
    "notification.autoNotify",
)
REDACTED_DIAGNOSTIC_FIELDS = {"app.appSecret", "recipient.openId"}
```

Add this function before `load_json_fields`:

```python
def validate_global_secret_permissions(path):
    if os.name != "posix":
        return
    try:
        mode = stat.S_IMODE(Path(path).stat().st_mode)
    except OSError as exc:
        raise ConfigError("unable to inspect global configuration permissions") from exc
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        raise ConfigError(
            "global configuration containing app.appSecret must be private; "
            "run chmod 600 on the file"
        )
```

In `load_json_fields`, immediately after `_read_json_object` returns a non-`None` payload, add the permission gate before returning any values:

```python
    if (
        source == "global"
        and isinstance(payload.get("app"), dict)
        and "appSecret" in payload["app"]
    ):
        validate_global_secret_permissions(path)
```

Add the safe output functions after `auto_notify_enabled`:

```python
def format_source_diagnostics(resolution):
    lines = []
    for dotted in DIAGNOSTIC_FIELDS:
        source = resolution.sources[dotted]
        suffix = " (redacted)" if dotted in REDACTED_DIAGNOSTIC_FIELDS else ""
        lines.append("%s: %s%s" % (dotted, source, suffix))
    return "\n".join(lines)


def legacy_migration_message(legacy_env_file):
    try:
        exists = Path(legacy_env_file).is_file()
    except OSError:
        exists = False
    if not exists:
        return None
    return (
        "Legacy feishu-connector/.env detected but Phase 2 configuration is "
        "incomplete or invalid. Move appSecret to the global JSON or process "
        "environment, move project overrides to "
        ".config/feishu-connector/config.json, and remove the old file after "
        "migration. The legacy .env was not read."
    )
```

- [ ] **Step 4: Run focused security tests and the full configuration suite**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_config.py' -v
```

Expected: all tests PASS. On POSIX, both permission tests run; elsewhere they are explicitly skipped.

- [ ] **Step 5: Commit the security layer**

```bash
git add feishu-connector/scripts/feishu_config.py feishu-connector/tests/test_config.py
git commit -m "feat: secure Feishu configuration diagnostics"
```

---

### Task 4: Integrate Phase 2 configuration into the CLI

**Files:**
- Modify: `feishu-connector/scripts/feishu_notify.py`
- Modify: `feishu-connector/tests/test_cli.py`
- Test unchanged: `feishu-connector/tests/test_client.py`
- Test unchanged: `feishu-connector/tests/test_adapter.py`

**Interfaces:**
- Consumes: all stable interfaces from `feishu_config.py`.
- Preserves: `Config`, `ConfigError`, and `parse_bool` imports from `feishu_notify`; `FeishuClient(config)`; `send`; `task`; `task --auto`; `--source Codex|OpenCode`; exit codes `0`, `3`, `4`, and `5`.
- Produces: global option `--project-root PATH` and read-only subcommand `config`.
- `main` changes to `main(argv=None, environ=None, config_paths=None, client_factory=FeishuClient, stdout=None, stderr=None, cwd=None, home=None, git_runner=subprocess.run)`; the test-only Phase 1 `env_file` injection is removed because `.env` must not be read.

- [ ] **Step 1: Convert CLI fixtures to JSON and add failing integration tests**

Replace `FakeClient` in `test_cli.py` with:

```python
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
```

Replace `CliTests.setUp` and `invoke` in `test_cli.py` with:

```python
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
```

Add `import json` and `from feishu_config import ConfigPaths`. Replace the four Phase 1 file-rewrite tests with these exact Phase 2 versions:

```python
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
```

Then add these integration tests:

```python
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
```

- [ ] **Step 2: Run CLI tests and verify the expected API failures**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
```

Expected: FAIL because `main` does not accept `config_paths`, `config` and `--project-root` are unknown, and the CLI still attempts Phase 1 `.env` loading.

- [ ] **Step 3: Replace Phase 1 configuration imports and parser options**

In `feishu_notify.py`, delete `CONFIG_KEYS`, the local `ConfigError`/`Config` definitions, `load_env_file`, `merged_settings`, `auto_notify_enabled`, `load_config`, and `default_env_file`. Remove the now-unused `dataclass` import only after confirming `JsonResponse` still needs it; therefore keep `from dataclasses import dataclass`.

Add `import subprocess` and this import block after the standard-library imports:

```python
from feishu_config import (
    Config,
    ConfigError,
    auto_notify_enabled,
    build_config_paths,
    format_source_diagnostics,
    legacy_migration_message,
    load_config,
    missing_required_fields,
    parse_bool,
    resolve_settings,
)
```

At the start of `build_parser`, before creating subparsers, add:

```python
    parser.add_argument(
        "--project-root",
        type=Path,
        help="override project root used for .config/feishu-connector/config.json",
    )
```

After configuring the task parser, add:

```python
    subparsers.add_parser(
        "config", help="show effective configuration sources without network access"
    )
```

- [ ] **Step 4: Replace `main` with source-aware Phase 2 control flow**

Use this exact `main` implementation:

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
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)
    paths = config_paths
    try:
        if paths is None:
            paths = build_config_paths(
                explicit_project_root=args.project_root,
                cwd=Path.cwd() if cwd is None else cwd,
                home=Path.home() if home is None else home,
                git_runner=git_runner,
            )

        if args.command == "config":
            resolution = load_config(paths, environ)
            print(format_source_diagnostics(resolution), file=stdout)
            return EXIT_OK

        if args.command == "task" and args.auto:
            settings = resolve_settings(paths, environ)
            if not settings.values["notification.autoNotify"]:
                print("Feishu auto notification disabled; nothing sent", file=stdout)
                if missing_required_fields(settings):
                    migration = legacy_migration_message(paths.legacy_env_file)
                    if migration is not None:
                        print(migration, file=stderr)
                return EXIT_OK

        resolution = load_config(paths, environ)
        config = resolution.config
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
        if paths is not None:
            migration = legacy_migration_message(paths.legacy_env_file)
            if migration is not None:
                print(migration, file=stderr)
        return EXIT_CONFIG
    except ConnectorError as exc:
        code_text = " code=%s" % exc.code if exc.code is not None else ""
        print(
            "Feishu notification warning [%s]%s: %s"
            % (exc.category, code_text, exc),
            file=stderr,
        )
        return _connector_exit_code(exc)
```

Do not call `auto_notify_enabled` from `main`; keep it re-exported for compatibility and direct callers. The `task --auto` branch uses `resolve_settings` once so it can both gate the send and detect incomplete migration state without reading `.env`.

- [ ] **Step 5: Run CLI tests, then client and adapter regressions**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_cli.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_client.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_adapter.py' -v
```

Expected: all three commands PASS. The config-command test proves the fake client is never constructed; adapter tests prove the existing CLI argv boundary still works.

- [ ] **Step 6: Commit CLI integration**

```bash
git add feishu-connector/scripts/feishu_notify.py feishu-connector/tests/test_cli.py
git commit -m "feat: integrate layered Feishu configuration"
```

---

### Task 5: Migration, configuration, and Skill documentation

**Files:**
- Delete: `feishu-connector/.env.example`
- Modify: `feishu-connector/README.md`
- Modify: `feishu-connector/docs/USAGE.md`
- Modify: `feishu-connector/skills/feishu-notify/SKILL.md`
- Modify: `feishu-connector/tests/test_skill_contract.py`
- Preserve: `.gitignore` entry `feishu-connector/.env`

**Interfaces:**
- Consumes: the CLI syntax and source rules from Task 4.
- Produces: documentation that an operator can use without reading the implementation, plus static contract tests that prevent regression to Phase 1 `.env` instructions.
- The Skill continues invoking only `send` and `task --auto`; it does not read either JSON file or any Secret.

- [ ] **Step 1: Add failing documentation contract tests**

Replace `test_marks_json_configuration_as_phase_two` in `test_skill_contract.py` with:

```python
    def test_documents_phase_two_paths_priority_and_diagnostics(self):
        for phrase in (
            "~/.config/feishu-connector/config.json",
            ".config/feishu-connector/config.json",
            "环境变量 > 项目 JSON > 全局 JSON",
            "--project-root",
            "feishu_notify.py config",
            "(redacted)",
        ):
            self.assertIn(phrase, self.readme)

    def test_documents_secret_policy_and_env_migration(self):
        for phrase in (
            "项目 JSON 中禁止出现 `appSecret`",
            "chmod 600",
            "不再读取",
            "完成迁移后",
        ):
            self.assertIn(phrase, self.readme)
```

Add this assertion to `test_documents_configuration_and_both_commands`:

```python
        self.assertNotIn("复制为 `.env`", self.readme)
```

- [ ] **Step 2: Run the contract tests and confirm old documentation fails them**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
```

Expected: FAIL because README still says Phase 1 reads `.env` and marks JSON configuration as future work.

- [ ] **Step 3: Replace README configuration and migration sections with exact Phase 2 guidance**

In `feishu-connector/README.md`, replace “本地配置” and “二期” with sections containing these exact rules and examples:

````markdown
## 配置

连接器按叶子字段合并三层配置，优先级固定为：**环境变量 > 项目 JSON > 全局 JSON**。高优先级没有出现的字段继续继承低优先级值；显式 `null`、未知字段、错误类型和空字符串都会在联网前报配置错误。

全局兜底路径是 `~/.config/feishu-connector/config.json`：

```json
{
  "app": {
    "appId": "cli_example",
    "appSecret": "example-secret"
  },
  "recipient": {
    "openId": "ou_example"
  },
  "notification": {
    "autoNotify": false
  }
}
```

在 POSIX 系统上，只要全局 JSON 含 `appSecret`，就必须执行 `chmod 600 ~/.config/feishu-connector/config.json`，不得授予 group 或 other 读写权限。

项目覆盖路径是 `<项目根目录>/.config/feishu-connector/config.json`，允许提交 Git：

```json
{
  "recipient": {
    "openId": "ou_project_example"
  },
  "notification": {
    "autoNotify": true
  }
}
```

项目 JSON 中禁止出现 `appSecret`，即使为空或假值也会被拒绝。Secret 只能来自全局 JSON 或 `FEISHU_APP_SECRET`；Open ID 可以按仓库访问控制提交，但日志和诊断仍会脱敏。四个兼容环境变量是 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY`。

项目根目录依次取 CLI `--project-root`、当前 Git 仓库顶层目录、当前工作目录。需要显式指定时，把选项放在子命令前：

```bash
python3 feishu-connector/scripts/feishu_notify.py \
  --project-root /path/to/project send --message "测试消息"
```

## 配置诊断

以下命令只显示每个有效字段的来源，不显示配置值，也不发起网络请求：

```bash
python3 feishu-connector/scripts/feishu_notify.py config
```

示例输出：

```text
app.appId: project
app.appSecret: global (redacted)
recipient.openId: environment (redacted)
notification.autoNotify: project
```

## 从一期 `.env` 迁移

二期不再读取 `feishu-connector/.env`。把 App Secret 移至全局 JSON 或进程环境变量，把可提交的项目差异移至项目 JSON；原 `.env` 即使保留也不会生效。CLI 只在二期配置不完整或无效时检查旧文件是否存在并打印迁移提示，不读取或输出旧文件内容。验证新配置后删除旧文件；`.gitignore` 继续保护迁移期间遗留的真实 `.env`。
````

Keep the existing Feishu prerequisites, send/task syntax, failure isolation, exit codes, and offline-test sections. Replace the manual acceptance list with:

```markdown
## 手动端到端验收

只使用测试应用和测试用户，并在操作者明确授权真实发送后执行：

1. 创建权限为 `0600` 的全局 JSON，并创建只覆盖 `recipient.openId` 的项目 JSON。
2. 运行 `config`，确认四个字段来源正确且 Secret/Open ID 不出现在输出中。
3. 临时在项目 JSON 加入空的 `appSecret`，确认 CLI 以退出码 `3` 在联网前拒绝；随后删除该字段。
4. 运行 `send`，确认测试用户收到纯文本私聊。
5. 运行 `task`，确认状态、任务、摘要、仓库和分支正确展示。
6. 分别验证自动开关：关闭时任务结束不发送，开启时只发送一次。
7. 临时使用无效 Open ID，确认错误脱敏且通知失败不改变原任务结果。
```

- [ ] **Step 4: Update the concise usage guide and Skill policy**

In `feishu-connector/docs/USAGE.md`, replace Section 2 with this exact content:

````markdown
## 2. 配置与诊断

配置按叶子字段合并，优先级为 **环境变量 > 项目 JSON > 全局 JSON**。全局文件位于 `~/.config/feishu-connector/config.json`，可以包含 `app.appId`、`app.appSecret`、`recipient.openId` 和 `notification.autoNotify`；含 Secret 时在 POSIX 上执行：

```bash
chmod 600 ~/.config/feishu-connector/config.json
```

项目文件位于 `<项目根目录>/.config/feishu-connector/config.json`，允许提交并可覆盖 `app.appId`、`recipient.openId` 和 `notification.autoNotify`。项目 JSON 禁止出现 `appSecret`。环境变量 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY` 分别覆盖对应叶子字段。

项目根目录依次取 `--project-root`、当前 Git 仓库顶层目录、当前工作目录。检查有效来源且不联网：

```bash
python3 feishu-connector/scripts/feishu_notify.py config
```

二期不再读取 `feishu-connector/.env`。把 Secret 移到全局 JSON 或进程环境变量，把项目差异移到项目 JSON；确认 `config` 诊断正确后再删除旧 `.env`。检测和提示迁移时，CLI 不读取旧文件内容。
````

Replace the automatic-notification explanation in Section 5 with:

```markdown
仅当合并后的 `notification.autoNotify` 为 `true` 时发送。关闭或未配置时，命令会以成功的 no-op 结束；门控会校验全局 JSON、项目 JSON 和相关环境变量，但不要求完整发送凭据，也不请求网络。通知失败时 CLI 返回相应非零退出码；Codex 或自动化调用方必须把通知作为捕获的次要结果处理，保持原任务结果隔离。
```

In `feishu-connector/skills/feishu-notify/SKILL.md`, add this paragraph below the opening policy paragraph:

```markdown
The CLI resolves Phase 2 configuration itself using process environment, project JSON, and global JSON. This Skill must not open either JSON file, inspect the legacy `.env`, choose a recipient, or reproduce merge and secret rules. Repository instructions may supply `--project-root` only when they explicitly need to override Git/current-directory discovery; otherwise preserve the existing argv prefixes.
```

Delete `feishu-connector/.env.example`. Do not remove `feishu-connector/.env` from `.gitignore`.

- [ ] **Step 5: Run documentation contracts and scan for active Phase 1 instructions**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
rg -n '复制.*\.env|一期不读取.*config\.json|仅使用本地.*\.env' feishu-connector/README.md feishu-connector/docs/USAGE.md feishu-connector/skills/feishu-notify/SKILL.md
```

Expected: contract tests PASS; `rg` exits `1` with no matches. Historical requirements in `feishu-connector/specs/feishu-connector.md` and the Phase 1 plan remain unchanged.

- [ ] **Step 6: Commit documentation and migration cleanup**

```bash
git add feishu-connector/.env.example feishu-connector/README.md feishu-connector/docs/USAGE.md feishu-connector/skills/feishu-notify/SKILL.md feishu-connector/tests/test_skill_contract.py
git commit -m "docs: migrate Feishu connector to layered JSON configuration"
```

---

### Task 6: Full Phase 2 acceptance and regression gate

**Files:**
- Verify: `feishu-connector/scripts/feishu_config.py`
- Verify: `feishu-connector/scripts/feishu_notify.py`
- Verify: `feishu-connector/scripts/feishu_notify_adapter.py`
- Verify: `feishu-connector/tests/test_config.py`
- Verify: `feishu-connector/tests/test_cli.py`
- Verify: `feishu-connector/tests/test_client.py`
- Verify: `feishu-connector/tests/test_adapter.py`
- Verify: `feishu-connector/tests/test_skill_contract.py`
- Verify: `feishu-connector/README.md`
- Verify: `feishu-connector/docs/USAGE.md`

**Interfaces:**
- Verifies all Phase 2 acceptance criteria without real credentials or network access.
- Produces no source changes and no commit. Any failure returns execution to the task that owns the affected behavior.

- [ ] **Step 1: Map the specification acceptance criteria to automated evidence**

Confirm these exact mappings by test name:

| Section 14.7 criterion | Automated evidence |
|---|---|
| Three-source priority and field merge | `test_merges_environment_over_project_over_global_by_leaf` |
| Single project field inherits other values | `test_project_single_field_inherits_others_and_environment_can_complete` |
| Environment overrides only its matching field | `test_merges_environment_over_project_over_global_by_leaf` |
| Project `appSecret` rejected before network | `test_rejects_project_app_secret_even_when_null_empty_or_fake`, `test_invalid_project_secret_returns_3_before_network` |
| No global file needed when environment + project are complete | `test_project_single_field_inherits_others_and_environment_can_complete` |
| Unsafe global secret permissions rejected with repair guidance | `test_rejects_global_secret_file_with_group_or_other_read_write_bits` |
| Diagnostics accurate, redacted, and network-free | `test_source_diagnostics_show_sources_and_no_values`, `test_config_command_reports_sources_without_network_or_values` |
| `.env` is not read and migration is documented | `test_legacy_env_detection_never_reads_contents`, `test_legacy_env_yields_migration_guidance_without_being_read`, documentation contract tests |
| Future OpenCode reuse does not modify Feishu core | existing `--source OpenCode` CLI behavior, unchanged adapter tests, and Skill documentation preserving the CLI boundary |

- [ ] **Step 2: Run every offline test**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

Expected: all tests PASS; permission tests may be skipped only when `os.name != "posix"`; no test reaches `open.feishu.cn`.

- [ ] **Step 3: Verify syntax and CLI discovery without credentials**

Run:

```bash
python3 -m compileall -q feishu-connector/scripts feishu-connector/tests
python3 feishu-connector/scripts/feishu_notify.py --help
python3 feishu-connector/scripts/feishu_notify.py config --help
```

Expected: `compileall` exits `0`; main help lists `send`, `task`, `config`, and `--project-root`; config help exits `0` without loading configuration or making network requests.

- [ ] **Step 4: Verify repository safety and scope**

Run:

```bash
git diff --check
git status --short
git ls-files 'feishu-connector/.env' 'feishu-connector/.env.example'
rg -n 'requests|httpx|aiohttp' feishu-connector/scripts feishu-connector/tests
```

Expected: `git diff --check` prints nothing; status shows no uncommitted implementation changes; `git ls-files` prints neither a real `.env` nor the deleted example; dependency scan exits `1` with no third-party HTTP-library matches.

- [ ] **Step 5: Review the five focused commits**

Run:

```bash
git log -5 --oneline
```

Expected, newest first:

```text
<hash> docs: migrate Feishu connector to layered JSON configuration
<hash> feat: integrate layered Feishu configuration
<hash> feat: secure Feishu configuration diagnostics
<hash> feat: merge Feishu configuration by source
<hash> feat: add strict Feishu JSON configuration parser
```

Stop before real end-to-end sending. Real Feishu transmission requires the operator's configured test application, test user, and explicit authorization, and is not part of the default implementation run.
