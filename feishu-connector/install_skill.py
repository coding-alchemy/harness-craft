#!/usr/bin/env python3
import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path


MANAGED_FILES = {
    "SKILL.md": 0o644,
    "scripts/feishu_notify.py": 0o755,
    "scripts/feishu_connector/__init__.py": 0o644,
    "scripts/feishu_connector/client.py": 0o644,
    "scripts/feishu_connector/config.py": 0o644,
    "scripts/feishu_connector/cli.py": 0o644,
}


class InstallError(Exception):
    pass


def skill_source(connector_root):
    return Path(connector_root) / "skills" / "feishu-notify"


def skill_target(environ, home):
    codex_home = environ.get("CODEX_HOME")
    try:
        base = (
            Path(codex_home).expanduser()
            if codex_home
            else Path(home) / ".codex"
        )
        return base.absolute() / "skills" / "feishu-notify"
    except (RuntimeError, ValueError) as exc:
        raise InstallError("unable to resolve Skill installation target") from exc


def atomic_write(target, content, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".feishu-notify-",
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


def _read_sources(source):
    sources = {}
    for relative, mode in MANAGED_FILES.items():
        path = source / relative
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise InstallError("unable to read managed source: %s" % path) from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise InstallError("managed source is not a regular file: %s" % path)
        try:
            sources[relative] = (path.read_bytes(), mode)
        except OSError as exc:
            raise InstallError("unable to read managed source: %s" % path) from exc
    return sources


def _preflight(target_root, sources, force):
    write_required = {}
    for relative, (content, mode) in sources.items():
        target = target_root / relative
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            write_required[relative] = True
            continue
        except OSError as exc:
            raise InstallError("unable to inspect managed target: %s" % target) from exc

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


def _verify(target_root, sources):
    for relative, (content, mode) in sources.items():
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


def install(force=False, environ=None, home=None, connector_root=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    connector_root = (
        Path(__file__).resolve().parent
        if connector_root is None
        else connector_root
    )
    source = skill_source(connector_root)
    target = skill_target(environ, home)
    sources = _read_sources(source)
    write_required = _preflight(target, sources, force)
    for relative, required in write_required.items():
        if required:
            content, mode = sources[relative]
            atomic_write(target / relative, content, mode)
    _verify(target, sources)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install the feishu-notify Skill.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace conflicting managed Skill files",
    )
    arguments = parser.parse_args(argv)
    try:
        install(force=arguments.force)
    except (InstallError, OSError) as exc:
        print("Feishu Skill installation error: %s" % exc, file=sys.stderr)
        return 1
    print("Installed 6 feishu-notify Skill files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
