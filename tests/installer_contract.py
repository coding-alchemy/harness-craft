# -*- coding: utf-8 -*-
"""Skill 安装器共享测试合同。

online-media-reader 与 tech-doc-translator 的 install_skill.py 按批准设计保持
独立实现（不共享运行时代码）；本模块把两份完全相同的安装合同测试收拢为一
份参数化检查，由各模块 tests/test_installer_contract.py 以薄文件引用。合同：

- 受管清单由 skills/<skill-name>/ 递归派生：普通发布文件、POSIX 相对路径
  排序、权限归一化 0755/0644；缓存与编译字节码排除；符号链接拒绝；
- 目标 ${CODEX_HOME:-~/.codex}/skills/<skill-name>；
- 全量预检通过前不写任何文件；冲突默认拒绝；--force 只替换受管文件；
  未知目标文件保留；受管路径上的非普通文件（目录等）一律预检失败；
- Skill 源目录本身是符号链接时拒绝安装。
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache"}
CACHE_FILE_NAMES = {".DS_Store"}
CACHE_FILE_SUFFIXES = (".pyc", ".pyo")

CHECKS = []


def check(function):
    CHECKS.append(function)
    return function


@dataclass
class InstallerContract:
    module_root: Path
    skill_name: str
    forbidden_top_dirs: tuple
    prepare_fixtures: object = None
    out_of_source: object = None

    @property
    def error_prefix(self):
        return "%s Skill installation error: " % self.skill_name

    @property
    def source_skill(self):
        return self.module_root / "skills" / self.skill_name

    @property
    def installer(self):
        return self.module_root / "install_skill.py"


def publish_files(source):
    """按安装语义派生源码 Skill 的受管文件集合：相对路径 -> 规范权限。"""
    managed = {}
    for path in Path(source).rglob("*"):
        relative = path.relative_to(source)
        if relative.name in CACHE_FILE_NAMES or relative.name.endswith(
            CACHE_FILE_SUFFIXES
        ):
            continue
        if any(part in CACHE_DIR_NAMES for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        managed[relative.as_posix()] = (
            0o755 if path.stat().st_mode & 0o111 else 0o644
        )
    return managed


class InstallerSession:
    def __init__(self, contract, root):
        self.contract = contract
        self.root = root
        self.home = root / "home"
        self.codex_home = root / "codex"
        self.project = root / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.target = self.codex_home / "skills" / contract.skill_name

    def environ(self):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        env.pop("PYTHONPATH", None)
        return env

    def script_environ(self):
        """已安装脚本的运行环境：保留真实 HOME，第三方依赖按用户安装提供。"""
        env = os.environ.copy()
        env.update(
            {
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        env.pop("PYTHONPATH", None)
        return env

    def run(self, *arguments, installer=None):
        return subprocess.run(
            [sys.executable, str(installer or self.contract.installer), *arguments],
            cwd=self.project,
            env=self.environ(),
            capture_output=True,
            text=True,
            check=False,
        )

    def run_python(self, *arguments):
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=self.project,
            env=self.script_environ(),
            capture_output=True,
            text=True,
            check=False,
        )

    def installed_files(self):
        return {
            path.relative_to(self.target).as_posix()
            for path in self.target.rglob("*")
            if path.is_file()
        }

    def snapshot(self):
        return {
            path.relative_to(self.target).as_posix(): (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
                path.stat().st_ino,
                path.stat().st_mtime_ns,
            )
            for path in sorted(self.target.rglob("*"))
            if path.is_file()
        }


def make_session(contract):
    directory = tempfile.TemporaryDirectory()
    session = InstallerSession(contract, Path(directory.name))
    return directory, session


def copy_module(contract, root, name="temporary-source"):
    destination = root / name / contract.module_root.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(contract.module_root, destination)
    return destination


def assert_managed_files_match_source(contract, session):
    for relative, mode in publish_files(contract.source_skill).items():
        installed = session.target / relative
        assert stat.S_ISREG(installed.lstat().st_mode)
        assert (contract.source_skill / relative).read_bytes() == installed.read_bytes()
        assert mode == stat.S_IMODE(installed.stat().st_mode)


@check
def check_fresh_install_matches_source_publish_set(contract):
    directory, session = make_session(contract)
    try:
        result = session.run()

        assert result.returncode == 0, result.stderr
        managed = publish_files(contract.source_skill)
        assert result.stdout == (
            "Installed %d %s Skill files\n" % (len(managed), contract.skill_name)
        )
        installed_files = session.installed_files()
        assert installed_files == set(managed)
        assert "README.md" not in installed_files
        assert "install_skill.py" not in installed_files
        for development_dir in contract.forbidden_top_dirs:
            assert not (session.target / development_dir).exists()
        assert_managed_files_match_source(contract, session)
    finally:
        directory.cleanup()


@check
def check_install_is_idempotent(contract):
    directory, session = make_session(contract)
    try:
        first = session.run()
        assert first.returncode == 0, first.stderr
        before = session.snapshot()

        second = session.run()

        assert second.returncode == 0, second.stderr
        assert before == session.snapshot()
    finally:
        directory.cleanup()


@check
def check_differing_managed_file_requires_force_without_partial_write(contract):
    directory, session = make_session(contract)
    try:
        assert session.run().returncode == 0
        (session.target / "SKILL.md").write_bytes(b"user content")
        before = session.snapshot()

        result = session.run()

        assert result.returncode == 1
        assert result.stderr.startswith(contract.error_prefix), result.stderr
        assert not result.stderr.rstrip("\n").count("\n")
        assert before == session.snapshot()
    finally:
        directory.cleanup()


@check
def check_type_conflict_fails_before_any_write(contract):
    """受管路径上已存在目录等非普通文件时，无论 --force 与否都必须在写入前失败。"""
    directory, session = make_session(contract)
    try:
        conflict = max(publish_files(contract.source_skill))
        conflicting = session.target / conflict
        conflicting.mkdir(parents=True)
        for force in (False, True):
            arguments = ("--force",) if force else ()

            result = session.run(*arguments)

            assert result.returncode == 1, (force, result.stdout, result.stderr)
            assert result.stderr.startswith(contract.error_prefix), result.stderr
            assert "Traceback" not in result.stderr
            assert session.installed_files() == set(), (force, session.installed_files())
            assert conflicting.is_dir()
    finally:
        directory.cleanup()


@check
def check_force_updates_only_managed_files(contract):
    directory, session = make_session(contract)
    try:
        assert session.run().returncode == 0
        (session.target / "SKILL.md").write_bytes(b"user content")
        unknown = session.target / "notes.txt"
        unknown.write_bytes(b"keep me")

        result = session.run("--force")

        assert result.returncode == 0, result.stderr
        assert_managed_files_match_source(contract, session)
        assert unknown.read_bytes() == b"keep me"
    finally:
        directory.cleanup()


@check
def check_unknown_target_file_is_preserved(contract):
    directory, session = make_session(contract)
    try:
        session.target.mkdir(parents=True)
        unknown = session.target / "notes.txt"
        unknown.write_bytes(b"keep me")

        result = session.run()

        assert result.returncode == 0, result.stderr
        assert unknown.read_bytes() == b"keep me"
    finally:
        directory.cleanup()


@check
def check_invalid_codex_home_returns_concise_error(contract):
    directory, session = make_session(contract)
    try:
        session.codex_home.write_bytes(b"not a directory")

        result = session.run()

        assert result.returncode == 1
        assert result.stderr.startswith(contract.error_prefix), result.stderr
        assert "Traceback" not in result.stderr
    finally:
        directory.cleanup()


@check
def check_unknown_codex_home_user_returns_concise_error(contract):
    directory, session = make_session(contract)
    try:
        env = session.environ()
        env["CODEX_HOME"] = "~%s_installer_missing_user_987654321" % (
            contract.skill_name[:4]
        )
        result = subprocess.run(
            [sys.executable, str(contract.installer)],
            cwd=session.project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        assert result.stderr.startswith(contract.error_prefix), result.stderr
        assert "Traceback" not in result.stderr
    finally:
        directory.cleanup()


@check
def check_source_entry_symlink_is_rejected(contract):
    directory, session = make_session(contract)
    try:
        source_copy = copy_module(contract, session.root)
        skill = source_copy / "skills" / contract.skill_name
        entries = [path for path in skill.iterdir() if path.is_dir()]
        link = skill / (entries[0].name + "_linked")
        link.symlink_to(entries[0])

        result = session.run(installer=source_copy / "install_skill.py")

        assert result.returncode == 1
        assert result.stderr.startswith(contract.error_prefix), result.stderr
        assert "Traceback" not in result.stderr
        assert not session.target.exists()
    finally:
        directory.cleanup()


@check
def check_skill_root_symlink_is_rejected(contract):
    """Skill 源目录本身是符号链接时必须拒绝，不得跟随解析。"""
    directory, session = make_session(contract)
    try:
        source_copy = copy_module(contract, session.root)
        skills = source_copy / "skills"
        real = skills / (contract.skill_name + "-real")
        (skills / contract.skill_name).rename(real)
        (skills / contract.skill_name).symlink_to(real)

        result = session.run(installer=source_copy / "install_skill.py")

        assert result.returncode == 1
        assert result.stderr.startswith(contract.error_prefix), result.stderr
        assert "symbolic link" in result.stderr
        assert "Traceback" not in result.stderr
        assert not session.target.exists()
    finally:
        directory.cleanup()


@check
def check_cache_files_are_excluded_from_manifest(contract):
    directory, session = make_session(contract)
    try:
        source_copy = copy_module(contract, session.root)
        skill = source_copy / "skills" / contract.skill_name
        scripts = skill / "scripts"
        pycache = scripts / "__pycache__"
        pycache.mkdir(exist_ok=True)
        (pycache / "module.cpython-312.pyc").write_bytes(b"bytecode")
        (pycache / ".DS_Store").write_bytes(b"junk")
        pytest_cache = skill / ".pytest_cache"
        pytest_cache.mkdir(exist_ok=True)
        (pytest_cache / "CACHEDIR.TAG").write_bytes(b"tag")

        result = session.run(installer=source_copy / "install_skill.py")

        assert result.returncode == 0, result.stderr
        installed_files = session.installed_files()
        assert installed_files == set(publish_files(contract.source_skill))
        assert not any("__pycache__" in name for name in installed_files)
        assert not any(".DS_Store" in name for name in installed_files)
        assert not any(name.startswith(".pytest_cache") for name in installed_files)
    finally:
        directory.cleanup()


@check
def check_installed_skill_runs_without_source_repository(contract):
    directory, session = make_session(contract)
    try:
        source_copy = copy_module(contract, session.root)
        context = None
        if contract.prepare_fixtures is not None:
            context = contract.prepare_fixtures(source_copy, session.root)

        result = session.run(installer=source_copy / "install_skill.py")
        assert result.returncode == 0, result.stderr
        isolated_skill = session.root / "isolated" / contract.skill_name
        shutil.copytree(session.target, isolated_skill)
        shutil.rmtree(source_copy.parent)

        contract.out_of_source(session, isolated_skill, context)
        assert not source_copy.exists()
    finally:
        directory.cleanup()
