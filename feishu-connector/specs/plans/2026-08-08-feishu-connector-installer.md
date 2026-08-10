# Feishu Connector User Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the Feishu connector, shell-only adapter, and Codex Skill into stable macOS/Linux user-level locations using only Python 3 standard library code.

**Architecture:** A single `feishu-connector/install.py` builds an explicit managed-file manifest, preflights every target, and atomically publishes files. Installed shell launchers point at copied scripts under `~/.local/share`, while the copied Skill calls stable launcher names instead of repository-relative paths.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `os`, `pathlib`, `shlex`, `shutil`, `stat`, `tempfile`, `unittest`, `subprocess`); POSIX shell launchers; no third-party packages.

## Global Constraints

- First release supports macOS/Linux POSIX environments only; Windows must fail with a concise installer error.
- Default paths are `~/.local/share/feishu-connector/scripts`, `~/.local/bin`, and `${CODEX_HOME:-~/.codex}/skills/feishu-notify/SKILL.md`.
- `CODEX_HOME` affects only the Skill target.
- Never create, read, modify, migrate, or print global/project Feishu configuration, `.env` contents, App Secret, Token, or Open ID.
- Never delete directories or files outside the exact temporary files created by the current atomic write.
- Existing content that differs must fail before any target is changed unless `--force` is explicit.
- Every managed target's existing parent chain must be validated as directories before any publish write begins.
- If cleanup of a failed atomic write's restricted temporary file fails, retain that exact file and report its recovery path while preserving the original installation-error context.
- Stable launchers must preserve argv/stdin/stdout/stderr/exit-code boundaries and perform no evaluation of dynamic text.
- Installed runtime and installer use Python 3 standard library only.
- Implement with red-green-refactor and offline temporary-directory tests.

---

### Task 1: Build safe managed-file publishing primitives

**Files:**
- Create: `feishu-connector/install.py`
- Create: `feishu-connector/tests/test_install.py`

**Interfaces:**
- Produces: `InstallError`, immutable `ManagedFile(target: Path, content: bytes, mode: int)`, `preflight(files, force)`, and `publish(files, force)`.
- Later tasks consume `publish()` to install scripts, launchers, and Skill only after a full conflict preflight.

- [ ] **Step 1: Write failing publishing tests**

Create `feishu-connector/tests/test_install.py` with:

```python
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTOR_ROOT))

import install as installer  # noqa: E402


class PublishingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.target = self.root / "managed" / "file.txt"

    def item(self, content=b"new-content", mode=0o600):
        return installer.ManagedFile(self.target, content, mode)

    def test_publish_is_idempotent_for_identical_content_and_repairs_mode(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)

        installer.publish([self.item()], force=False)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))

    def test_preflight_rejects_conflict_before_changing_other_targets(self):
        first = self.root / "managed" / "first.txt"
        second = self.root / "managed" / "second.txt"
        second.parent.mkdir(parents=True)
        second.write_bytes(b"user-content")
        files = [
            installer.ManagedFile(first, b"first", 0o600),
            installer.ManagedFile(second, b"managed", 0o600),
        ]

        with self.assertRaisesRegex(installer.InstallError, "already exists"):
            installer.publish(files, force=False)

        self.assertFalse(first.exists())
        self.assertEqual(b"user-content", second.read_bytes())

    def test_force_replaces_only_the_exact_managed_target(self):
        sibling = self.root / "managed" / "keep.txt"
        sibling.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")
        sibling.write_bytes(b"keep-content")

        installer.publish([self.item()], force=True)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual(b"keep-content", sibling.read_bytes())

    def test_atomic_failure_preserves_original_and_cleans_temporary_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        with mock.patch("install.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(installer.InstallError, "unable to install"):
                installer.publish([self.item()], force=True)

        self.assertEqual(b"old-content", self.target.read_bytes())
        self.assertEqual([], list(self.target.parent.glob(".feishu-connector-*")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the publishing tests and verify RED**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_install.py' -v
```

Expected: ERROR because `feishu-connector/install.py` and `ManagedFile` do not exist.

- [ ] **Step 3: Implement explicit preflight and atomic publish**

Create `feishu-connector/install.py` with this initial content:

```python
#!/usr/bin/env python3
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class InstallError(Exception):
    pass


@dataclass(frozen=True)
class ManagedFile:
    target: Path
    content: bytes
    mode: int


def _existing_content(item):
    if item.target.is_symlink():
        return None
    try:
        if not item.target.exists():
            return None
        if not item.target.is_file():
            raise InstallError("managed target already exists and is not a file: %s" % item.target)
        return item.target.read_bytes()
    except OSError as exc:
        raise InstallError("unable to inspect managed target: %s" % item.target) from exc


def preflight(files, force):
    for item in files:
        existing = _existing_content(item)
        conflict = item.target.is_symlink() or (
            existing is not None and existing != item.content
        )
        if conflict and not force:
            raise InstallError("managed target already exists with different content: %s" % item.target)


def _atomic_write(item):
    item.target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".feishu-connector-",
        dir=str(item.target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(item.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, item.mode)
        os.replace(temporary, item.target)
    except OSError as exc:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise InstallError("unable to install managed file: %s" % item.target) from exc


def publish(files, force=False):
    files = tuple(files)
    preflight(files, force)
    for item in files:
        existing = _existing_content(item)
        if existing == item.content and not item.target.is_symlink():
            try:
                os.chmod(item.target, item.mode)
            except OSError as exc:
                raise InstallError("unable to set managed file permissions: %s" % item.target) from exc
            continue
        _atomic_write(item)
```

Do not add fallback deletion or recursive cleanup. Task 2 adds `argparse` only when the installer CLI starts using it.

- [ ] **Step 4: Run the publishing tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_install.py' -v
```

Expected: four tests pass and no files are written outside their temporary directory.

- [ ] **Step 5: Commit safe publishing primitives**

```bash
git add feishu-connector/install.py feishu-connector/tests/test_install.py
git commit -m "feat: add safe Feishu installer publishing"
```

---

### Task 2: Install scripts, stable launchers, and Codex Skill

**Files:**
- Modify: `feishu-connector/install.py`
- Modify: `feishu-connector/tests/test_install.py`
- Modify: `feishu-connector/skills/feishu-notify/SKILL.md`
- Modify: `feishu-connector/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: `ManagedFile` and `publish()` from Task 1; existing connector scripts and Skill source.
- Produces: `InstallLayout`, `default_layout()`, `build_manifest()`, `install_connector()`, and installer CLI `main()`; stable commands `feishu-notify` and `feishu-notify-adapter`.

- [ ] **Step 1: Add failing layout and installation tests**

Append these imports to `feishu-connector/tests/test_install.py`:

```python
import io
import json
import os
import subprocess
```

Append this test class before the `if __name__ == "__main__"` block:

```python
class InstallerIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.codex_home = self.root / "codex-home"
        self.layout = installer.default_layout(
            home=self.home,
            environ={"CODEX_HOME": str(self.codex_home), "PATH": ""},
        )

    def test_default_layout_uses_local_paths_and_codex_home_only_for_skill(self):
        self.assertEqual(
            self.home / ".local" / "share" / "feishu-connector" / "scripts",
            self.layout.scripts_dir,
        )
        self.assertEqual(self.home / ".local" / "bin", self.layout.bin_dir)
        self.assertEqual(
            self.codex_home / "skills" / "feishu-notify" / "SKILL.md",
            self.layout.skill_file,
        )

    def test_default_layout_rejects_non_posix_platforms(self):
        with mock.patch("install.os.name", "nt"):
            with self.assertRaisesRegex(installer.InstallError, "macOS/Linux only"):
                installer.default_layout(home=self.home, environ={})

    def test_installs_runtime_launchers_and_skill_without_creating_config(self):
        installed = installer.install_connector(
            connector_root=CONNECTOR_ROOT,
            layout=self.layout,
            force=False,
        )

        expected = {
            self.layout.scripts_dir / "feishu_config.py",
            self.layout.scripts_dir / "feishu_notify.py",
            self.layout.scripts_dir / "feishu_notify_adapter.py",
            self.layout.bin_dir / "feishu-notify",
            self.layout.bin_dir / "feishu-notify-adapter",
            self.layout.skill_file,
        }
        self.assertEqual(expected, set(installed))
        self.assertTrue(all(path.is_file() for path in expected))
        self.assertTrue(os.access(self.layout.bin_dir / "feishu-notify", os.X_OK))
        self.assertTrue(os.access(self.layout.bin_dir / "feishu-notify-adapter", os.X_OK))
        launcher = (self.layout.bin_dir / "feishu-notify").read_text(encoding="utf-8")
        self.assertIn(str(self.layout.scripts_dir / "feishu_notify.py"), launcher)
        self.assertNotIn(str(CONNECTOR_ROOT / "scripts"), launcher)
        self.assertFalse(
            (self.home / ".config" / "feishu-connector" / "config.json").exists()
        )
        skill = self.layout.skill_file.read_text(encoding="utf-8")
        self.assertIn("feishu-notify send --message", skill)
        self.assertIn("feishu-notify task --auto", skill)
        self.assertIn("feishu-notify-adapter", skill)
        self.assertNotIn("feishu-connector/scripts/", skill)

    def test_installed_cli_help_works_outside_source_repository(self):
        installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)
        outside = self.root / "outside-project"
        outside.mkdir()
        result = subprocess.run(
            [str(self.layout.bin_dir / "feishu-notify"), "--help"],
            cwd=outside,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Send plain-text Feishu messages", result.stdout)

    def test_installed_adapter_preserves_invalid_input_exit_code(self):
        installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)
        result = subprocess.run(
            [str(self.layout.bin_dir / "feishu-notify-adapter")],
            input="not json",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("Invalid adapter input", result.stderr)

    def test_launcher_preserves_one_hostile_argument_without_shell_evaluation(self):
        probe = self.root / "probe.py"
        probe.write_text(
            "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        launcher = self.root / "probe-launcher"
        launcher.write_bytes(installer._launcher(probe))
        launcher.chmod(0o755)
        marker = self.root / "must-not-exist"
        hostile = '"quoted"\n$(touch %s) `touch %s` --leading' % (marker, marker)

        result = subprocess.run(
            [str(launcher), hostile],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([hostile], json.loads(result.stdout))
        self.assertFalse(marker.exists())

    def test_main_warns_when_local_bin_is_not_on_path(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = installer.main(
            argv=[],
            environ={"CODEX_HOME": str(self.codex_home), "PATH": "/usr/bin"},
            home=self.home,
            connector_root=CONNECTOR_ROOT,
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(0, code)
        self.assertIn(str(self.layout.bin_dir), stdout.getvalue())
        self.assertIn("PATH", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_main_requires_force_to_update_a_differing_managed_file(self):
        installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)
        launcher = self.layout.bin_dir / "feishu-notify"
        launcher.write_text("user-modified\n", encoding="utf-8")

        refused_stderr = io.StringIO()
        refused = installer.main(
            argv=[],
            environ={"CODEX_HOME": str(self.codex_home), "PATH": ""},
            home=self.home,
            connector_root=CONNECTOR_ROOT,
            stdout=io.StringIO(),
            stderr=refused_stderr,
        )
        self.assertEqual(1, refused)
        self.assertEqual("user-modified\n", launcher.read_text(encoding="utf-8"))

        updated = installer.main(
            argv=["--force"],
            environ={"CODEX_HOME": str(self.codex_home), "PATH": ""},
            home=self.home,
            connector_root=CONNECTOR_ROOT,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        self.assertEqual(0, updated)
        self.assertIn("exec python3", launcher.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Update Skill contract tests before the Skill text**

In `feishu-connector/tests/test_skill_contract.py`, change the command assertions to the installed command contract:

```python
    def test_explicit_send_uses_installed_send_command(self):
        self.assertIn("feishu-notify send --message", self.skill)
        self.assertNotIn("feishu-connector/scripts/", self.skill)

    def test_documents_shell_only_safe_fallback_adapter(self):
        self.assertIn("## Shell-only execution fallback", self.skill)
        fallback = self.skill.split("## Shell-only execution fallback", 1)[1]
        for required in (
            "feishu-notify-adapter",
            "separate stdin/input-data channel",
            "feishu-notify send --message",
            "feishu-notify task --auto",
            "cannot provide separate stdin data",
        ):
            self.assertIn(required, fallback)
        self.assertNotIn("temporary JSON file", fallback)
        self.assertNotIn("python3 -c", fallback)

    def test_automatic_send_uses_installed_task_auto_gate(self):
        self.assertIn("feishu-notify task --auto", self.skill)
```

Replace the three old tests that assert `feishu_notify.py` or `feishu_notify_adapter.py`; retain the argv-safety, five-field, privacy, and result-isolation tests unchanged.

- [ ] **Step 3: Run installer and Skill tests and verify RED**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_install.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
```

Expected: installer integration tests error because layout/install functions are missing; Skill contract tests fail because the current Skill still contains repository-relative script paths.

- [ ] **Step 4: Replace repository-relative commands in the Skill**

Apply these exact command substitutions in `feishu-connector/skills/feishu-notify/SKILL.md` while preserving all safety rules:

```text
python3 feishu-connector/scripts/feishu_notify.py
    -> feishu-notify

python3 feishu-connector/scripts/feishu_notify_adapter.py
    -> feishu-notify-adapter

feishu_notify.py send --message
    -> feishu-notify send --message

feishu_notify.py task --auto
    -> feishu-notify task --auto
```

The opening paragraph must read:

```markdown
Use the installed `feishu-notify` CLI. Do not implement Feishu HTTP requests in this Skill, do not read or print App Secret or access tokens, and do not send messages unless one of the workflows below applies.
```

- [ ] **Step 5: Implement layout, manifest, launchers, and installer CLI**

Add these imports to `feishu-connector/install.py`:

```python
import shlex
import sys
```

Append the following implementation after `publish()`:

```python
@dataclass(frozen=True)
class InstallLayout:
    scripts_dir: Path
    bin_dir: Path
    skill_file: Path


def _absolute_path(path):
    return Path(path).expanduser().resolve()


def default_layout(home=None, environ=None):
    if os.name != "posix":
        raise InstallError("the Feishu connector installer supports macOS/Linux only")
    environ = os.environ if environ is None else environ
    home = _absolute_path(Path.home() if home is None else home)
    codex_home_value = environ.get("CODEX_HOME")
    codex_home = _absolute_path(codex_home_value) if codex_home_value else home / ".codex"
    return InstallLayout(
        scripts_dir=home / ".local" / "share" / "feishu-connector" / "scripts",
        bin_dir=home / ".local" / "bin",
        skill_file=codex_home / "skills" / "feishu-notify" / "SKILL.md",
    )


def _launcher(script):
    return (
        "#!/bin/sh\nexec python3 %s \"$@\"\n" % shlex.quote(str(script))
    ).encode("utf-8")


def build_manifest(connector_root, layout):
    connector_root = _absolute_path(connector_root)
    script_names = (
        "feishu_config.py",
        "feishu_notify.py",
        "feishu_notify_adapter.py",
    )
    files = []
    for name in script_names:
        source = connector_root / "scripts" / name
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise InstallError("unable to read connector source file: %s" % source) from exc
        files.append(ManagedFile(layout.scripts_dir / name, content, 0o644))

    files.extend(
        (
            ManagedFile(
                layout.bin_dir / "feishu-notify",
                _launcher(layout.scripts_dir / "feishu_notify.py"),
                0o755,
            ),
            ManagedFile(
                layout.bin_dir / "feishu-notify-adapter",
                _launcher(layout.scripts_dir / "feishu_notify_adapter.py"),
                0o755,
            ),
        )
    )
    skill_source = connector_root / "skills" / "feishu-notify" / "SKILL.md"
    try:
        skill_content = skill_source.read_bytes()
    except OSError as exc:
        raise InstallError("unable to read Skill source: %s" % skill_source) from exc
    files.append(ManagedFile(layout.skill_file, skill_content, 0o644))
    return tuple(files)


def install_connector(connector_root, layout, force=False):
    files = build_manifest(connector_root, layout)
    publish(files, force=force)
    installed = tuple(item.target for item in files)
    for target in installed:
        if not target.is_file():
            raise InstallError("installed file verification failed: %s" % target)
    for launcher in (
        layout.bin_dir / "feishu-notify",
        layout.bin_dir / "feishu-notify-adapter",
    ):
        if not os.access(launcher, os.X_OK):
            raise InstallError("installed launcher is not executable: %s" % launcher)
    return installed


def build_parser():
    parser = argparse.ArgumentParser(
        description="Install the Feishu connector for the current user"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace differing files managed by this installer",
    )
    return parser


def main(
    argv=None,
    environ=None,
    home=None,
    connector_root=None,
    stdout=None,
    stderr=None,
):
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)
    connector_root = (
        Path(__file__).resolve().parent
        if connector_root is None
        else _absolute_path(connector_root)
    )
    try:
        layout = default_layout(home=home, environ=environ)
        installed = install_connector(connector_root, layout, force=args.force)
    except InstallError as exc:
        print("Feishu connector installation error: %s" % exc, file=stderr)
        return 1

    print("Installed %d Feishu connector files" % len(installed), file=stdout)
    path_entries = environ.get("PATH", "").split(os.pathsep)
    if str(layout.bin_dir) not in path_entries:
        print(
            "%s is not on PATH; add it before using feishu-notify"
            % layout.bin_dir,
            file=stdout,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `argparse` back to the imports now that `build_parser()` uses it. Do not add `shutil` or recursive copy; the manifest must remain explicit.

- [ ] **Step 6: Run installer, Skill, and existing connector tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_install.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_skill_contract.py' -v
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

Expected: installer and Skill tests pass; the full suite reports `OK` with no failures or errors and performs no real Feishu requests.

- [ ] **Step 7: Commit the complete user-level installer**

```bash
git add \
  feishu-connector/install.py \
  feishu-connector/tests/test_install.py \
  feishu-connector/skills/feishu-notify/SKILL.md \
  feishu-connector/tests/test_skill_contract.py
git commit -m "feat: add Feishu connector user installer"
```

---

### Task 3: Document installation and run an isolated install smoke test

**Files:**
- Modify: `feishu-connector/README.md:17-123`
- Modify: `feishu-connector/docs/USAGE.md:5-69`
- Verify: `feishu-connector/specs/2026-08-08-feishu-connector-installer-design.md`

**Interfaces:**
- Consumes: `python3 feishu-connector/install.py [--force]`, installed `feishu-notify`, and installed `feishu-notify-adapter` from Task 2.
- Produces: user-facing install/update/PATH/source-run instructions and a clean end-to-end offline install verification.

- [ ] **Step 1: Add README installation instructions**

Insert this section before `## 配置` in `feishu-connector/README.md`:

````markdown
## 用户级安装

第一版安装器支持 macOS/Linux，只依赖 Python 3 标准库。在仓库根目录运行：

```bash
python3 feishu-connector/install.py
```

安装器把运行文件复制到 `~/.local/share/feishu-connector`，把 `feishu-notify` 和 `feishu-notify-adapter` 放到 `~/.local/bin`，并把 Skill 安装到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。如果 `~/.local/bin` 不在 `PATH`，安装器会输出设置提示，但不会修改 Shell 配置。

重复安装相同内容是安全的。更新内容不同时，安装器默认拒绝覆盖；确认要更新受管文件后运行：

```bash
python3 feishu-connector/install.py --force
```

安装器不会创建或修改飞书配置、`.env`、Secret、Token 或 Open ID。安装后可以从任意项目目录运行 `feishu-notify`；下文的 `python3 feishu-connector/scripts/feishu_notify.py` 命令保留为源码仓库内的直接运行方式。
````

- [ ] **Step 2: Add the concise installation path to the usage guide**

Insert a new `## 2. 用户级安装` section after “开始前”, then renumber later headings. Use this content:

```markdown
## 2. 用户级安装

在 macOS/Linux 的仓库根目录运行 `python3 feishu-connector/install.py`。安装后的稳定命令是 `feishu-notify` 和 `feishu-notify-adapter`；若安装器提示 `~/.local/bin` 不在 `PATH`，按提示加入后重新打开 Shell。更新已安装的受管文件使用 `python3 feishu-connector/install.py --force`。

安装器不创建飞书配置。以下章节继续说明全局 JSON、项目 JSON 和环境变量。源码仓库内也可以继续使用 `python3 feishu-connector/scripts/feishu_notify.py`。
```

- [ ] **Step 3: Run an isolated installer smoke test without touching the real HOME**

Do not invoke the CLI installer against the real user home. Run the injectable Python API with explicit temporary paths:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_install.py' -v
```

Expected: all installer tests pass; every write remains under a `TemporaryDirectory`.

- [ ] **Step 4: Run the complete repository verification gate**

Run:

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
python3 -m compileall -q feishu-connector/install.py feishu-connector/scripts feishu-connector/tests
python3 feishu-connector/install.py --help
python3 feishu-connector/scripts/feishu_notify.py --help
git diff --check
git status --short --branch
```

Expected: all tests pass with zero failures/errors; compileall and help commands exit `0`; `git diff --check` is silent; status contains only intended installer and documentation changes.

- [ ] **Step 5: Verify no installer path or documentation regression remains**

Run:

```bash
rg -n 'feishu-connector/scripts/' feishu-connector/skills/feishu-notify/SKILL.md
rg -n 'feishu-notify|feishu-notify-adapter|install.py --force|\.local/bin' feishu-connector/README.md feishu-connector/docs/USAGE.md
rg -n 'appSecret|tenant_access_token|Authorization|openId' feishu-connector/install.py feishu-connector/tests/test_install.py
```

Expected: the Skill search returns no repository-relative script path; README/USAGE contain installed command and update guidance; installer occurrences of sensitive field names, if any, appear only in assertions that confirm those files are not accessed and never contain real values.

- [ ] **Step 6: Commit installation documentation**

```bash
git add feishu-connector/README.md feishu-connector/docs/USAGE.md
git commit -m "docs: add Feishu connector installation guide"
```
