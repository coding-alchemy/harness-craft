#!/usr/bin/env python3
import argparse
import ctypes
import errno
import os
import secrets
import shlex
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class InstallError(Exception):
    pass


@dataclass(frozen=True)
class ManagedFile:
    target: Path
    content: bytes
    mode: int


@dataclass
class _PreparedFile:
    item: ManagedFile
    target: Path
    directory_descriptors: list
    directory_entries: list
    missing_parent_parts: tuple

    @property
    def directory_descriptor(self):
        return self.directory_descriptors[-1]


def _identity(file_stat):
    return file_stat.st_dev, file_stat.st_ino


def _directory_flags():
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _close_prepared(prepared_files):
    for prepared in prepared_files:
        for descriptor in reversed(prepared.directory_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        prepared.directory_descriptors.clear()


def _append_existing_directory(prepared, name):
    parent_descriptor = prepared.directory_descriptor
    descriptor = None
    try:
        named_identity = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(named_identity.st_mode):
            raise InstallError(
                "managed target parent symlink is not allowed: %s" % prepared.item.target
            )
        if not stat.S_ISDIR(named_identity.st_mode):
            raise InstallError(
                "managed target parent already exists and is not a directory: %s"
                % prepared.item.target
            )
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
        opened_identity = os.fstat(descriptor)
        if _identity(named_identity) != _identity(opened_identity):
            raise InstallError(
                "managed target parent changed during preflight: %s"
                % prepared.item.target
            )
        prepared.directory_entries.append((name, _identity(opened_identity)))
        prepared.directory_descriptors.append(descriptor)
        descriptor = None
    except FileNotFoundError:
        raise
    except InstallError:
        raise
    except (OSError, ValueError) as exc:
        raise InstallError(
            "unable to inspect managed target parent: %s" % prepared.item.target
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _inspect_parent(item):
    target = _absolute_path(item.target, "managed target path")
    prepared = _PreparedFile(item, target, [], [], ())
    try:
        root_descriptor = os.open(target.anchor, _directory_flags())
        prepared.directory_descriptors.append(root_descriptor)
        parent_parts = target.parent.parts[1:]
        for index, name in enumerate(parent_parts):
            try:
                _append_existing_directory(prepared, name)
            except FileNotFoundError:
                prepared.missing_parent_parts = tuple(parent_parts[index:])
                break
        return prepared
    except Exception:
        _close_prepared((prepared,))
        raise


def _verify_parent_chain(prepared):
    try:
        for index, (name, expected_identity) in enumerate(
            prepared.directory_entries
        ):
            current_identity = os.stat(
                name,
                dir_fd=prepared.directory_descriptors[index],
                follow_symlinks=False,
            )
            opened_identity = os.fstat(prepared.directory_descriptors[index + 1])
            if (
                not stat.S_ISDIR(current_identity.st_mode)
                or _identity(current_identity) != expected_identity
                or _identity(opened_identity) != expected_identity
            ):
                raise OSError("directory identity changed")
    except (OSError, ValueError) as exc:
        raise InstallError(
            "managed target parent changed after preflight: %s" % prepared.item.target
        ) from exc


def _verify_target_identity(prepared, expected_identity):
    try:
        current_identity = os.stat(
            prepared.target.name,
            dir_fd=prepared.directory_descriptor,
            follow_symlinks=False,
        )
    except (OSError, ValueError) as exc:
        raise InstallError(
            "managed target changed after preflight: %s" % prepared.item.target
        ) from exc
    if _identity(current_identity) != expected_identity:
        raise InstallError(
            "managed target changed after preflight: %s" % prepared.item.target
        )


def _complete_parent(prepared):
    _verify_parent_chain(prepared)
    for name in prepared.missing_parent_parts:
        try:
            os.mkdir(name, dir_fd=prepared.directory_descriptor)
        except FileExistsError:
            pass
        except (OSError, ValueError) as exc:
            raise InstallError(
                "unable to install managed file: %s" % prepared.item.target
            ) from exc
        try:
            _append_existing_directory(prepared, name)
        except FileNotFoundError as exc:
            raise InstallError(
                "managed target parent changed during preflight: %s"
                % prepared.item.target
            ) from exc
    prepared.missing_parent_parts = ()
    _verify_parent_chain(prepared)


def _open_existing(prepared):
    try:
        named_identity = os.stat(
            prepared.target.name,
            dir_fd=prepared.directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return "missing", None, None, None
    except (OSError, ValueError) as exc:
        raise InstallError(
            "unable to inspect managed target: %s" % prepared.item.target
        ) from exc
    if stat.S_ISLNK(named_identity.st_mode):
        return "symlink", None, None, _identity(named_identity)
    if not stat.S_ISREG(named_identity.st_mode):
        raise InstallError(
            "managed target already exists and is not a file: %s"
            % prepared.item.target
        )

    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            prepared.target.name,
            flags,
            dir_fd=prepared.directory_descriptor,
        )
        opened_identity = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_identity.st_mode)
            or _identity(opened_identity) != _identity(named_identity)
        ):
            raise OSError("managed target identity changed during inspection")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        return "file", content, descriptor, _identity(opened_identity)
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise InstallError(
            "unable to inspect managed target: %s" % prepared.item.target
        ) from exc


def _check_conflict(prepared, force):
    kind, content, descriptor, _ = _open_existing(prepared)
    permissions_differ = False
    try:
        if (
            descriptor is not None
            and kind == "file"
            and content == prepared.item.content
        ):
            permissions_differ = (
                stat.S_IMODE(os.fstat(descriptor).st_mode)
                != prepared.item.mode
            )
    except OSError as exc:
        raise InstallError(
            "unable to inspect managed file permissions: %s"
            % prepared.item.target
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not force and permissions_differ:
        raise InstallError(
            "managed target permissions differ; rerun with --force: %s"
            % prepared.item.target
        )
    if not force and (
        kind == "symlink"
        or (kind == "file" and content != prepared.item.content)
    ):
        raise InstallError(
            "managed target already exists with different content: %s"
            % prepared.item.target
        )


@contextmanager
def _prepared_files(files, force):
    prepared_files = []
    try:
        for item in files:
            prepared = _inspect_parent(item)
            prepared_files.append(prepared)
            if not prepared.missing_parent_parts:
                _check_conflict(prepared, force)
        for prepared in prepared_files:
            _complete_parent(prepared)
            _check_conflict(prepared, force)
        yield tuple(prepared_files)
    finally:
        _close_prepared(prepared_files)


def preflight(files, force):
    with _prepared_files(tuple(files), force):
        pass


def _create_temporary(directory_descriptor):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(100):
        basename = ".feishu-connector-%s" % secrets.token_hex(8)
        try:
            descriptor = os.open(
                basename,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
            return descriptor, basename
        except FileExistsError:
            continue
    raise OSError("unable to allocate a unique temporary file")


def _fsync_directory(directory_descriptor):
    try:
        os.fsync(directory_descriptor)
    except OSError as exc:
        unsupported_errors = {
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if exc.errno not in unsupported_errors:
            raise


def _descriptor_candidates(descriptor):
    candidates = []
    try:
        import fcntl

        get_path = getattr(fcntl, "F_GETPATH", None)
        if get_path is not None:
            value = fcntl.fcntl(descriptor, get_path, b"\0" * 1024)
            encoded = value.split(b"\0", 1)[0]
            if encoded:
                candidates.append(Path(os.fsdecode(encoded)))
    except (ImportError, OSError, ValueError):
        pass
    try:
        candidates.append(Path(os.readlink("/proc/self/fd/%d" % descriptor)))
    except (OSError, ValueError):
        pass
    return tuple(candidates)


def _descriptor_path(descriptor):
    candidates = _descriptor_candidates(descriptor)

    descriptor_identity = _identity(os.fstat(descriptor))
    for candidate in candidates:
        try:
            candidate_identity = os.stat(candidate, follow_symlinks=False)
        except (OSError, ValueError):
            continue
        if (
            stat.S_ISDIR(candidate_identity.st_mode)
            and _identity(candidate_identity) == descriptor_identity
        ):
            return candidate
    return None


def _descriptor_file_path(descriptor, expected_identity):
    for candidate in _descriptor_candidates(descriptor):
        try:
            candidate_identity = os.stat(candidate, follow_symlinks=False)
        except (OSError, ValueError):
            continue
        if (
            stat.S_ISREG(candidate_identity.st_mode)
            and _identity(candidate_identity) == expected_identity
        ):
            return candidate
    return None


def _recovery_path(prepared, temporary_basename, temporary_identity):
    parent = _descriptor_path(prepared.directory_descriptor)
    if parent is None:
        return None
    candidate = parent / temporary_basename
    try:
        candidate_identity = os.stat(candidate, follow_symlinks=False)
    except (OSError, ValueError):
        return None
    if _identity(candidate_identity) != _identity(temporary_identity):
        return None
    return candidate


def _verify_temporary_identity(prepared, temporary_basename, expected_identity):
    try:
        current = os.stat(
            temporary_basename,
            dir_fd=prepared.directory_descriptor,
            follow_symlinks=False,
        )
    except (OSError, ValueError) as exc:
        raise InstallError(
            "unable to verify temporary file identity: %s"
            % prepared.item.target
        ) from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or _identity(current) != expected_identity
    ):
        raise InstallError(
            "temporary file identity changed during publication: %s"
            % prepared.item.target
        )


def _rename_noreplace(source, target, directory_descriptor):
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function_name = "renameatx_np"
        flags = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function_name = "renameat2"
        flags = 0x00000001  # RENAME_NOREPLACE
    else:
        raise InstallError(
            "atomic no-clobber publication is unsupported on this platform"
        )

    try:
        rename = getattr(library, function_name)
    except AttributeError as exc:
        raise InstallError(
            "atomic no-clobber publication is unavailable on this system"
        ) from exc
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = rename(
        directory_descriptor,
        os.fsencode(source),
        directory_descriptor,
        os.fsencode(target),
        flags,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            os.strerror(error_number),
            target,
        )
    raise OSError(error_number, os.strerror(error_number), target)


def _atomic_write(prepared, replace_existing):
    descriptor = None
    handle = None
    temporary_basename = None
    temporary_identity = None
    try:
        _verify_parent_chain(prepared)
        descriptor, temporary_basename = _create_temporary(
            prepared.directory_descriptor
        )
        temporary_identity = os.fstat(descriptor)
        named_identity = os.stat(
            temporary_basename,
            dir_fd=prepared.directory_descriptor,
            follow_symlinks=False,
        )
        if _identity(temporary_identity) != _identity(named_identity):
            raise OSError("temporary file identity changed during creation")

        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        os.fchmod(handle.fileno(), prepared.item.mode)
        handle.write(prepared.item.content)
        handle.flush()
        os.fsync(handle.fileno())
        _verify_parent_chain(prepared)
        expected_identity = _identity(temporary_identity)
        _verify_temporary_identity(
            prepared,
            temporary_basename,
            expected_identity,
        )
        if replace_existing:
            os.replace(
                temporary_basename,
                prepared.target.name,
                src_dir_fd=prepared.directory_descriptor,
                dst_dir_fd=prepared.directory_descriptor,
            )
            _verify_target_identity(prepared, expected_identity)
            temporary_basename = None
        else:
            try:
                _rename_noreplace(
                    temporary_basename,
                    prepared.target.name,
                    prepared.directory_descriptor,
                )
            except FileExistsError as exc:
                raise InstallError(
                    "managed target changed after preflight: %s"
                    % prepared.item.target
                ) from exc
            _verify_target_identity(prepared, expected_identity)
            temporary_basename = None
        temporary_basename = None
        _fsync_directory(prepared.directory_descriptor)
        _verify_parent_chain(prepared)
        _verify_target_identity(prepared, expected_identity)
    except (InstallError, OSError, ValueError) as exc:
        if temporary_basename is None:
            if isinstance(exc, InstallError):
                raise
            raise InstallError(
                "unable to install managed file: %s" % prepared.item.target
            ) from exc

        open_descriptor = handle.fileno() if handle is not None else descriptor
        if temporary_identity is None:
            try:
                temporary_identity = os.fstat(open_descriptor)
            except OSError as identity_exc:
                try:
                    os.fchmod(open_descriptor, 0o600)
                    restriction_description = "restricted to mode 0600"
                except OSError as restriction_exc:
                    restriction_description = "restriction failed: %s" % restriction_exc
                try:
                    parent = _descriptor_path(prepared.directory_descriptor)
                except (OSError, ValueError):
                    parent = None
                recovery_candidate = (
                    str(parent / temporary_basename)
                    if parent is not None
                    else "no safe recovery pathname is available"
                )
                raise InstallError(
                    "unable to install managed file: %s (original error: %s); "
                    "temporary file identity could not be verified; "
                    "recovery candidate: %s (%s; identity error: %s)"
                    % (
                        prepared.item.target,
                        exc,
                        recovery_candidate,
                        restriction_description,
                        identity_exc,
                    )
                ) from exc

        restriction_error = None
        try:
            os.fchmod(open_descriptor, 0o600)
        except OSError as restriction_exc:
            restriction_error = restriction_exc

        cleanup_error = None
        retained_reason = None
        try:
            try:
                _verify_parent_chain(prepared)
            except InstallError:
                retained_reason = "managed target parent changed"
            if retained_reason is None:
                current_temporary_identity = os.stat(
                    temporary_basename,
                    dir_fd=prepared.directory_descriptor,
                    follow_symlinks=False,
                )
                if _identity(current_temporary_identity) != _identity(temporary_identity):
                    retained_reason = "temporary file identity changed"
                else:
                    retained_reason = (
                        "safe identity-bound pathname cleanup is unavailable"
                    )
        except FileNotFoundError:
            retained_reason = "temporary file name is no longer present"
        except (OSError, ValueError) as cleanup_exc:
            cleanup_error = cleanup_exc

        recovery = _recovery_path(
            prepared,
            temporary_basename,
            temporary_identity,
        )
        if recovery is None:
            recovery = _descriptor_file_path(
                open_descriptor,
                _identity(temporary_identity),
            )
        recovery_description = (
            str(recovery)
            if recovery is not None
            else "no safe recovery pathname is available"
        )

        if restriction_error is not None:
            raise InstallError(
                "unable to install managed file: %s (original error: %s); "
                "temporary file retained for recovery but could not be restricted: "
                "%s (cleanup issue: %s; restriction failed: %s)"
                % (
                    prepared.item.target,
                    exc,
                    recovery_description,
                    cleanup_error or retained_reason,
                    restriction_error,
                )
            ) from exc
        if cleanup_error is not None:
            retained_reason = "cleanup failed: %s" % cleanup_error
        raise InstallError(
            "unable to install managed file: %s (original error: %s); "
            "temporary file retained for recovery: %s (%s)"
            % (
                prepared.item.target,
                exc,
                recovery_description,
                retained_reason,
            )
        ) from exc
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        elif descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def publish(files, force=False):
    files = tuple(files)
    with _prepared_files(files, force) as prepared_files:
        for prepared in prepared_files:
            _verify_parent_chain(prepared)
            kind, content, descriptor, expected_identity = _open_existing(prepared)
            try:
                if kind == "file" and content == prepared.item.content:
                    _verify_parent_chain(prepared)
                    _verify_target_identity(prepared, expected_identity)
                    try:
                        opened_stat = os.fstat(descriptor)
                        current_mode = stat.S_IMODE(opened_stat.st_mode)
                        if current_mode == prepared.item.mode:
                            continue
                        if not force:
                            raise InstallError(
                                "managed target permissions differ; rerun with "
                                "--force: %s" % prepared.item.target
                            )
                    except InstallError:
                        raise
                    except OSError as exc:
                        raise InstallError(
                            "unable to inspect managed file permissions: %s"
                            % prepared.item.target
                        ) from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            if not force and (
                kind == "symlink"
                or (kind == "file" and content != prepared.item.content)
            ):
                raise InstallError(
                    "managed target already exists with different content: %s"
                    % prepared.item.target
                )
            _atomic_write(
                prepared,
                replace_existing=force or kind != "missing",
            )


@dataclass(frozen=True)
class InstallLayout:
    scripts_dir: Path
    bin_dir: Path
    skill_file: Path


def _absolute_path(path, description="filesystem path"):
    try:
        absolute = Path(path).expanduser().absolute()
        if "\x00" in str(absolute):
            raise ValueError("embedded null character")
        os.fsencode(absolute)
        return absolute
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
        raise InstallError("unable to normalize %s" % description) from exc


def default_layout(home=None, environ=None):
    if os.name != "posix":
        raise InstallError("the Feishu connector installer supports macOS/Linux only")
    environ = os.environ if environ is None else environ
    try:
        home_value = Path.home() if home is None else home
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallError("unable to determine HOME") from exc
    home = _absolute_path(home_value, "HOME")
    codex_home_value = environ.get("CODEX_HOME")
    codex_home = (
        _absolute_path(codex_home_value, "CODEX_HOME")
        if codex_home_value
        else home / ".codex"
    )
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
    connector_root = _absolute_path(connector_root, "connector source path")
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
    try:
        connector_root = (
            Path(__file__).resolve().parent
            if connector_root is None
            else _absolute_path(connector_root, "connector source path")
        )
        layout = default_layout(home=home, environ=environ)
        installed = install_connector(connector_root, layout, force=args.force)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        exc = InstallError("unable to access the installation filesystem")
        print("Feishu connector installation error: %s" % exc, file=stderr)
        return 1
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
