#!/usr/bin/env python3
"""把 online-media-reader Skill 的受管文件安装到 Codex Skill 目录。

受管清单从 skills/online-media-reader/ 递归派生：只接受普通发布文件，
排除缓存与编译字节码；符号链接与非普通文件直接失败。写入采用同目录
临时文件与原子替换，冲突默认拒绝，--force 只替换受管文件，清单外目标
文件保持不变。
"""
import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path


SKILL_NAME = "online-media-reader"
ERROR_PREFIX = "%s Skill installation error: " % SKILL_NAME
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache"}
CACHE_FILE_NAMES = {".DS_Store"}
CACHE_FILE_SUFFIXES = (".pyc", ".pyo")


class InstallError(Exception):
    pass


def skill_source(module_root):
    return Path(module_root) / "skills" / SKILL_NAME


def skill_target(environ, home):
    codex_home = environ.get("CODEX_HOME")
    try:
        base = (
            Path(codex_home).expanduser()
            if codex_home
            else Path(home) / ".codex"
        )
        return base.absolute() / "skills" / SKILL_NAME
    except (RuntimeError, ValueError) as exc:
        raise InstallError("unable to resolve Skill installation target") from exc


def normalized_mode(file_stat):
    return 0o755 if file_stat.st_mode & 0o111 else 0o644


def read_sources(source):
    if source.is_symlink():
        raise InstallError("Skill source directory is a symbolic link: %s" % source)
    if not source.is_dir():
        raise InstallError("Skill source directory is missing: %s" % source)
    sources = {}
    for path in sorted(source.rglob("*")):
        relative_path = path.relative_to(source)
        if relative_path.name in CACHE_FILE_NAMES or relative_path.name.endswith(
            CACHE_FILE_SUFFIXES
        ):
            continue
        if any(part in CACHE_DIR_NAMES for part in relative_path.parts):
            continue
        relative = relative_path.as_posix()
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise InstallError("unable to read managed source: %s" % path) from exc
        if path.is_symlink():
            raise InstallError(
                "managed source is a symbolic link: %s" % path
            )
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise InstallError(
                "managed source is not a regular file: %s" % path
            )
        try:
            sources[relative] = (path.read_bytes(), normalized_mode(file_stat))
        except OSError as exc:
            raise InstallError("unable to read managed source: %s" % path) from exc
    if not sources:
        raise InstallError("Skill source directory has no managed files: %s" % source)
    return sources


def atomic_write(target, content, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s-" % SKILL_NAME,
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def preflight(target_root, sources, force):
    write_required = {}
    for relative in sorted(sources):
        content, mode = sources[relative]
        target = target_root / relative
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            write_required[relative] = True
            continue
        except OSError as exc:
            raise InstallError("unable to inspect managed target: %s" % target) from exc
        if not stat.S_ISREG(target_stat.st_mode):
            raise InstallError(
                "managed target exists and is not a regular file; "
                "remove it and rerun: %s" % target
            )

        matches = False
        if stat.S_ISREG(target_stat.st_mode):
            try:
                matches = (
                    target.read_bytes() == content
                    and stat.S_IMODE(target_stat.st_mode) == mode
                )
            except OSError as exc:
                raise InstallError(
                    "unable to inspect managed target: %s" % target
                ) from exc
        if not matches and not force:
            raise InstallError(
                "managed target differs; rerun with --force: %s" % target
            )
        write_required[relative] = not matches
    return write_required


def verify(target_root, sources):
    for relative in sorted(sources):
        content, mode = sources[relative]
        target = target_root / relative
        try:
            target_stat = target.lstat()
            installed_content = target.read_bytes()
        except OSError as exc:
            raise InstallError("unable to verify managed target: %s" % target) from exc
        if (
            not stat.S_ISREG(target_stat.st_mode)
            or installed_content != content
            or stat.S_IMODE(target_stat.st_mode) != mode
        ):
            raise InstallError("managed target verification failed: %s" % target)


def install(force=False, environ=None, home=None, module_root=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    module_root = (
        Path(__file__).resolve().parent if module_root is None else module_root
    )
    source = skill_source(module_root)
    target = skill_target(environ, home)
    sources = read_sources(source)
    write_required = preflight(target, sources, force)
    for relative in sorted(write_required):
        if write_required[relative]:
            content, mode = sources[relative]
            atomic_write(target / relative, content, mode)
    verify(target, sources)
    return len(sources)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install the %s Skill." % SKILL_NAME
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace conflicting managed Skill files",
    )
    arguments = parser.parse_args(argv)
    try:
        installed = install(force=arguments.force)
    except (InstallError, OSError) as exc:
        print("%s%s" % (ERROR_PREFIX, exc), file=sys.stderr)
        return 1
    print("Installed %d %s Skill files" % (installed, SKILL_NAME))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
