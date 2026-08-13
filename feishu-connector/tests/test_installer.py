import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = CONNECTOR_ROOT / "install_skill.py"
MANAGED_FILES = {
    "SKILL.md": 0o644,
    "scripts/feishu_notify.py": 0o755,
    "scripts/feishu_connector/__init__.py": 0o644,
    "scripts/feishu_connector/client.py": 0o644,
    "scripts/feishu_connector/config.py": 0o644,
    "scripts/feishu_connector/cli.py": 0o644,
}


class SkillInstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.codex_home = self.root / "codex"
        self.project = self.root / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.target = self.codex_home / "skills" / "feishu-notify"
        self.source = CONNECTOR_ROOT / "skills" / "feishu-notify"
        self.environ = os.environ.copy()
        self.environ.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        self.environ.pop("PYTHONPATH", None)

    def run_installer(self, *arguments, installer=INSTALLER):
        return subprocess.run(
            [sys.executable, str(installer), *arguments],
            cwd=self.project,
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )

    def managed_snapshot(self):
        return {
            relative: (
                (self.target / relative).read_bytes(),
                stat.S_IMODE((self.target / relative).stat().st_mode),
            )
            for relative in MANAGED_FILES
        }

    def assert_managed_files_match_source(self):
        for relative, mode in MANAGED_FILES.items():
            installed = self.target / relative
            self.assertTrue(stat.S_ISREG(installed.lstat().st_mode))
            self.assertEqual(
                (self.source / relative).read_bytes(),
                installed.read_bytes(),
            )
            self.assertEqual(mode, stat.S_IMODE(installed.stat().st_mode))

    def test_installs_self_contained_skill_into_codex_home(self):
        result = self.run_installer()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "Installed 6 feishu-notify Skill files\n",
            result.stdout,
        )
        installed_files = {
            path.relative_to(self.target).as_posix()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(set(MANAGED_FILES), installed_files)
        self.assert_managed_files_match_source()

    def test_install_is_idempotent(self):
        first = self.run_installer()
        self.assertEqual(0, first.returncode, first.stderr)
        before = self.managed_snapshot()

        second = self.run_installer()

        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(before, self.managed_snapshot())

    def test_differing_managed_file_requires_force(self):
        self.assertEqual(0, self.run_installer().returncode)
        conflicting = self.target / "SKILL.md"
        conflicting.write_bytes(b"user content")
        before = self.managed_snapshot()

        result = self.run_installer()

        self.assertEqual(1, result.returncode)
        self.assertTrue(
            result.stderr.startswith("Feishu Skill installation error:"),
            result.stderr,
        )
        self.assertEqual(before, self.managed_snapshot())

    def test_force_updates_only_managed_files(self):
        self.assertEqual(0, self.run_installer().returncode)
        (self.target / "SKILL.md").write_bytes(b"user content")
        unknown = self.target / "notes.txt"
        unknown.write_bytes(b"keep me")

        result = self.run_installer("--force")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assert_managed_files_match_source()
        self.assertEqual(b"keep me", unknown.read_bytes())

    def test_unknown_target_file_is_preserved(self):
        self.target.mkdir(parents=True)
        unknown = self.target / "notes.txt"
        unknown.write_bytes(b"keep me")

        result = self.run_installer()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"keep me", unknown.read_bytes())

    def test_installed_cli_help_works_without_source_repository(self):
        source_copy = self.root / "temporary-source" / "feishu-connector"
        shutil.copytree(CONNECTOR_ROOT, source_copy)
        result = self.run_installer(installer=source_copy / "install_skill.py")
        self.assertEqual(0, result.returncode, result.stderr)
        isolated_skill = self.root / "isolated" / "feishu-notify"
        shutil.copytree(self.target, isolated_skill)
        shutil.rmtree(source_copy.parent)

        help_result = subprocess.run(
            [
                sys.executable,
                str(isolated_skill / "scripts" / "feishu_notify.py"),
                "--help",
            ],
            cwd=self.project,
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertIn("usage:", help_result.stdout)
        self.assertIn("rich", help_result.stdout)
        self.assertIn("rich-text", help_result.stdout)

    def test_install_does_not_create_configuration(self):
        result = self.run_installer()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], list(self.home.rglob("config.json")))
        self.assertEqual([], list(self.project.rglob("config.json")))

    def test_invalid_codex_home_returns_concise_error(self):
        self.codex_home.write_bytes(b"not a directory")

        result = self.run_installer()

        self.assertEqual(1, result.returncode)
        self.assertTrue(
            result.stderr.startswith("Feishu Skill installation error:"),
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_codex_home_user_returns_concise_error(self):
        self.environ["CODEX_HOME"] = "~feishu_skill_missing_user_987654321"

        result = self.run_installer()

        self.assertEqual(1, result.returncode)
        self.assertTrue(
            result.stderr.startswith("Feishu Skill installation error:"),
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
