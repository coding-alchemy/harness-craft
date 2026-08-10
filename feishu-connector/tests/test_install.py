import errno
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTOR_ROOT))

import install as installer  # noqa: E402


class PublishingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.target = self.root / "managed" / "file.txt"

    def item(self, content=b"new-content", mode=0o600):
        return installer.ManagedFile(self.target, content, mode)

    def test_repeated_standalone_preflight_closes_descriptors_on_success_and_failure(self):
        self.target.parent.mkdir(parents=True)
        conflict = self.target.parent / "conflict.txt"
        conflict.write_bytes(b"user-content")
        conflicting_item = installer.ManagedFile(conflict, b"managed-content", 0o600)
        original_open = os.open
        original_close = os.close
        opened = []
        closed = []

        def tracking_open(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def tracking_close(descriptor):
            closed.append(descriptor)
            return original_close(descriptor)

        with mock.patch("install.os.open", side_effect=tracking_open):
            with mock.patch("install.os.close", side_effect=tracking_close):
                for _ in range(3):
                    self.assertIsNone(installer.preflight([self.item()], force=False))
                with self.assertRaisesRegex(installer.InstallError, "already exists"):
                    installer.preflight(
                        [self.item(), conflicting_item],
                        force=False,
                    )

        self.assertGreater(len(opened), 0)
        self.assertCountEqual(opened, closed)

    def test_parent_fstat_failure_closes_just_opened_descriptor(self):
        self.target.parent.mkdir(parents=True)
        operations = (
            ("preflight", lambda: installer.preflight([self.item()], force=False)),
            ("publish preparation", lambda: installer.publish([self.item()])),
        )

        for operation_name, operation in operations:
            with self.subTest(operation=operation_name):
                original_open = os.open
                original_close = os.close
                opened = []
                closed = []

                def tracking_open(*args, **kwargs):
                    descriptor = original_open(*args, **kwargs)
                    opened.append(descriptor)
                    return descriptor

                def tracking_close(descriptor):
                    closed.append(descriptor)
                    return original_close(descriptor)

                def failing_fstat(descriptor):
                    self.assertEqual(opened[-1], descriptor)
                    raise OSError("fstat denied")

                try:
                    with mock.patch("install.os.open", side_effect=tracking_open):
                        with mock.patch("install.os.close", side_effect=tracking_close):
                            with mock.patch("install.os.fstat", side_effect=failing_fstat):
                                with self.assertRaisesRegex(
                                    installer.InstallError,
                                    "unable to inspect managed target parent",
                                ) as caught:
                                    operation()

                    self.assertEqual(
                        "unable to inspect managed target parent: %s" % self.target,
                        str(caught.exception),
                    )
                    self.assertGreater(len(opened), 1)
                    self.assertCountEqual(opened, closed)
                finally:
                    for descriptor in set(opened) - set(closed):
                        original_close(descriptor)

    def test_recovery_path_does_not_require_path_stat_keyword_support(self):
        self.target.parent.mkdir(parents=True)
        temporary = self.target.parent / ".feishu-connector-recovery"
        temporary.write_bytes(b"recovery")
        directory_descriptor = os.open(
            self.target.parent,
            installer._directory_flags(),
        )
        prepared = installer._PreparedFile(
            self.item(),
            self.target,
            [directory_descriptor],
            [],
            (),
        )
        self.addCleanup(installer._close_prepared, (prepared,))

        with mock.patch("install._descriptor_path", return_value=self.target.parent):
            with mock.patch.object(
                Path,
                "stat",
                side_effect=TypeError("follow_symlinks is unsupported"),
            ):
                recovery = installer._recovery_path(
                    prepared,
                    temporary.name,
                    os.stat(temporary, follow_symlinks=False),
                )

        self.assertEqual(temporary, recovery)

    def test_publish_is_idempotent_for_identical_content_and_repairs_mode(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)

        installer.publish([self.item()], force=True)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))

    def test_nonforce_mode_repair_is_rejected_without_changing_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)

        with self.assertRaisesRegex(installer.InstallError, "permissions differ"):
            installer.publish([self.item()], force=False)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(self.target.stat().st_mode))
        self.assertEqual([], list(self.target.parent.glob(".feishu-connector-*")))

    def test_mode_repair_replaces_target_without_changing_hard_linked_alias(self):
        self.target.parent.mkdir(parents=True)
        unmanaged = self.root / "unmanaged.txt"
        unmanaged.write_bytes(b"new-content")
        unmanaged.chmod(0o644)
        os.link(unmanaged, self.target)

        installer.publish([self.item()], force=True)

        self.assertNotEqual(unmanaged.stat().st_ino, self.target.stat().st_ino)
        self.assertEqual(0o644, stat.S_IMODE(unmanaged.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))

    def test_idempotent_publish_accepts_hard_link_when_mode_is_already_correct(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o600)
        unmanaged_alias = self.root / "unmanaged-alias.txt"
        os.link(self.target, unmanaged_alias)

        installer.publish([self.item()], force=False)

        self.assertEqual(self.target.stat().st_ino, unmanaged_alias.stat().st_ino)
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))
        self.assertEqual(b"new-content", unmanaged_alias.read_bytes())

    def test_mode_repair_never_chmods_the_existing_inode(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)
        unmanaged_alias = self.root / "unmanaged-alias.txt"
        os.link(self.target, unmanaged_alias)
        existing_identity = (self.target.stat().st_dev, self.target.stat().st_ino)
        original_fchmod = os.fchmod

        def reject_existing_inode_chmod(descriptor, mode):
            descriptor_stat = os.fstat(descriptor)
            self.assertNotEqual(
                existing_identity,
                (descriptor_stat.st_dev, descriptor_stat.st_ino),
            )
            return original_fchmod(descriptor, mode)

        with mock.patch("install.os.fchmod", side_effect=reject_existing_inode_chmod):
            installer.publish([self.item()], force=True)

        self.assertNotEqual(self.target.stat().st_ino, unmanaged_alias.stat().st_ino)
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))
        self.assertEqual(0o644, stat.S_IMODE(unmanaged_alias.stat().st_mode))

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

    def test_missing_target_created_during_publish_is_not_overwritten(self):
        self.target.parent.mkdir(parents=True)
        original_create_temporary = installer._create_temporary

        def create_temporary_then_race(directory_descriptor):
            temporary = original_create_temporary(directory_descriptor)
            descriptor = os.open(
                self.target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_descriptor,
            )
            try:
                os.write(descriptor, b"concurrent-user-content")
            finally:
                os.close(descriptor)
            return temporary

        with mock.patch(
            "install._create_temporary",
            side_effect=create_temporary_then_race,
        ):
            with self.assertRaisesRegex(installer.InstallError, "changed"):
                installer.publish([self.item()], force=False)

        self.assertEqual(b"concurrent-user-content", self.target.read_bytes())
        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertEqual(0o600, stat.S_IMODE(temporary_files[0].stat().st_mode))

    def test_force_overwrites_target_created_during_publish(self):
        self.target.parent.mkdir(parents=True)
        original_create_temporary = installer._create_temporary

        def create_temporary_then_race(directory_descriptor):
            temporary = original_create_temporary(directory_descriptor)
            descriptor = os.open(
                self.target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_descriptor,
            )
            try:
                os.write(descriptor, b"concurrent-user-content")
            finally:
                os.close(descriptor)
            return temporary

        with mock.patch(
            "install._create_temporary",
            side_effect=create_temporary_then_race,
        ):
            installer.publish([self.item()], force=True)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual([], list(self.target.parent.glob(".feishu-connector-*")))

    def test_new_target_publication_does_not_unlink_a_temporary_path(self):
        self.target.parent.mkdir(parents=True)

        with mock.patch(
            "install.os.unlink",
            side_effect=AssertionError("publication must not unlink by pathname"),
        ):
            installer.publish([self.item()])

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual([], list(self.target.parent.glob(".feishu-connector-*")))

    def test_temporary_path_replacement_during_rename_is_detected_and_preserved(self):
        self.target.parent.mkdir(parents=True)
        original_rename_noreplace = installer._rename_noreplace
        replacement_content = b"concurrent-unrelated-content"
        replaced_temporary = None

        def replace_temporary_then_rename(source, target, directory_descriptor):
            nonlocal replaced_temporary
            replaced_temporary = self.target.parent / (str(source) + ".original")
            os.rename(
                source,
                replaced_temporary.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_descriptor,
            )
            try:
                os.write(descriptor, replacement_content)
            finally:
                os.close(descriptor)
            return original_rename_noreplace(
                source,
                target,
                directory_descriptor,
            )

        with mock.patch(
            "install._rename_noreplace",
            side_effect=replace_temporary_then_rename,
        ):
            with self.assertRaisesRegex(
                installer.InstallError,
                "managed target changed",
            ) as caught:
                installer.publish([self.item(mode=0o755)])

        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertIsNotNone(replaced_temporary)
        self.assertEqual(b"new-content", replaced_temporary.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(replaced_temporary.stat().st_mode))
        self.assertIn(str(replaced_temporary), str(caught.exception))
        self.assertEqual(replacement_content, self.target.read_bytes())

    def test_force_source_replacement_is_restricted_and_reported(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")
        original_replace = os.replace
        replacement_content = b"concurrent-unrelated-content"
        replaced_temporary = None

        def replace_temporary_source(source, target, *args, **kwargs):
            nonlocal replaced_temporary
            source_directory = kwargs["src_dir_fd"]
            replaced_temporary = self.target.parent / (str(source) + ".original")
            os.rename(
                source,
                replaced_temporary.name,
                src_dir_fd=source_directory,
                dst_dir_fd=source_directory,
            )
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_directory,
            )
            try:
                os.write(descriptor, replacement_content)
            finally:
                os.close(descriptor)
            return original_replace(source, target, *args, **kwargs)

        with mock.patch("install.os.replace", side_effect=replace_temporary_source):
            with self.assertRaisesRegex(
                installer.InstallError,
                "managed target changed",
            ) as caught:
                installer.publish([self.item(mode=0o755)], force=True)

        self.assertIsNotNone(replaced_temporary)
        self.assertEqual(b"new-content", replaced_temporary.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(replaced_temporary.stat().st_mode))
        self.assertIn(str(replaced_temporary), str(caught.exception))
        self.assertEqual(replacement_content, self.target.read_bytes())

    def test_preflight_rejects_permission_drift_before_any_publish(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)
        first = self.target.parent / "first.txt"
        files = [
            installer.ManagedFile(first, b"first-content", 0o600),
            self.item(),
        ]

        with self.assertRaisesRegex(installer.InstallError, "permissions differ"):
            installer.preflight(files, force=False)
        with self.assertRaisesRegex(installer.InstallError, "permissions differ"):
            installer.publish(files, force=False)

        self.assertFalse(first.exists())
        self.assertEqual(0o644, stat.S_IMODE(self.target.stat().st_mode))

    def test_preflight_rejects_blocked_parent_before_changing_other_targets(self):
        first = self.root / "valid" / "first.txt"
        blocked = self.root / "blocked"
        second = blocked / "second.txt"
        blocked.write_bytes(b"not-a-directory")
        files = [
            installer.ManagedFile(first, b"first", 0o600),
            installer.ManagedFile(second, b"second", 0o600),
        ]

        with self.assertRaisesRegex(installer.InstallError, "parent"):
            installer.publish(files, force=False)

        self.assertFalse(first.exists())
        self.assertEqual(b"not-a-directory", blocked.read_bytes())

    def test_preflight_rejects_dangling_parent_symlink_before_any_write(self):
        first = self.root / "valid" / "first.txt"
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "missing-directory", target_is_directory=True)
        second = dangling / "second.txt"
        files = [
            installer.ManagedFile(first, b"first", 0o600),
            installer.ManagedFile(second, b"second", 0o600),
        ]

        with self.assertRaisesRegex(installer.InstallError, "parent symlink"):
            installer.publish(files, force=False)

        self.assertFalse(first.exists())
        self.assertTrue(dangling.is_symlink())

    def test_publish_fails_closed_when_parent_is_replaced_after_preflight(self):
        redirected_parent = self.root / "redirected-parent"
        retained_parent = self.root / "retained-parent"
        self.target.parent.mkdir(parents=True)
        redirected_parent.mkdir()
        self.target.write_bytes(b"old-content")
        redirected_target = redirected_parent / self.target.name
        redirected_target.write_bytes(b"redirected-content")
        original_prepared_files = installer._prepared_files

        @contextmanager
        def prepare_then_replace_parent(files, force):
            with original_prepared_files(files, force) as prepared:
                self.target.parent.rename(retained_parent)
                self.target.parent.symlink_to(
                    redirected_parent,
                    target_is_directory=True,
                )
                yield prepared

        with mock.patch(
            "install._prepared_files",
            side_effect=prepare_then_replace_parent,
        ):
            with self.assertRaisesRegex(installer.InstallError, "parent changed"):
                installer.publish([self.item()], force=True)

        self.assertEqual(b"old-content", (retained_parent / self.target.name).read_bytes())
        self.assertEqual(b"redirected-content", redirected_target.read_bytes())
        self.assertEqual([], list(redirected_parent.glob(".feishu-connector-*")))

    def test_publish_fails_closed_when_parent_is_replaced_during_replace(self):
        redirected_parent = self.root / "redirected-parent"
        retained_parent = self.root / "retained-parent"
        self.target.parent.mkdir(parents=True)
        redirected_parent.mkdir()
        self.target.write_bytes(b"old-content")
        redirected_target = redirected_parent / self.target.name
        redirected_target.write_bytes(b"redirected-content")
        original_replace = os.replace

        def replace_parent_then_publish(source, target, *args, **kwargs):
            self.target.parent.rename(retained_parent)
            self.target.parent.symlink_to(redirected_parent, target_is_directory=True)
            return original_replace(source, target, *args, **kwargs)

        with mock.patch("install.os.replace", side_effect=replace_parent_then_publish):
            with self.assertRaisesRegex(installer.InstallError, "parent changed"):
                installer.publish([self.item()], force=True)

        self.assertEqual(b"new-content", (retained_parent / self.target.name).read_bytes())
        self.assertEqual(b"redirected-content", redirected_target.read_bytes())

    def test_mode_repair_fails_closed_when_parent_changes_during_staging(self):
        redirected_parent = self.root / "redirected-parent"
        retained_parent = self.root / "retained-parent"
        self.target.parent.mkdir(parents=True)
        redirected_parent.mkdir()
        self.target.write_bytes(b"new-content")
        self.target.chmod(0o644)
        redirected_target = redirected_parent / self.target.name
        redirected_target.write_bytes(b"redirected-content")
        redirected_target.chmod(0o640)
        original_fchmod = os.fchmod

        def chmod_then_replace_parent(descriptor, mode):
            original_fchmod(descriptor, mode)
            self.target.parent.rename(retained_parent)
            self.target.parent.symlink_to(redirected_parent, target_is_directory=True)

        with mock.patch("install.os.fchmod", side_effect=chmod_then_replace_parent):
            with self.assertRaisesRegex(installer.InstallError, "parent changed"):
                installer.publish([self.item()], force=True)

        retained_target = retained_parent / self.target.name
        self.assertEqual(0o644, stat.S_IMODE(retained_target.stat().st_mode))
        self.assertEqual(b"redirected-content", redirected_target.read_bytes())
        self.assertEqual(0o640, stat.S_IMODE(redirected_target.stat().st_mode))

    def test_force_replaces_only_the_exact_managed_target(self):
        sibling = self.root / "managed" / "keep.txt"
        sibling.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")
        sibling.write_bytes(b"keep-content")

        installer.publish([self.item()], force=True)

        self.assertEqual(b"new-content", self.target.read_bytes())
        self.assertEqual(b"keep-content", sibling.read_bytes())

    def test_atomic_failure_preserves_original_and_retains_safe_recovery_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        with mock.patch("install.os.replace", side_effect=OSError("replace failed")):
            with mock.patch(
                "install.os.unlink",
                side_effect=AssertionError("failure cleanup must not unlink by pathname"),
            ):
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "temporary file retained for recovery",
                ):
                    installer.publish([self.item()], force=True)

        self.assertEqual(b"old-content", self.target.read_bytes())
        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertEqual(0o600, stat.S_IMODE(temporary_files[0].stat().st_mode))

    def test_successful_publication_fsyncs_parent_directory(self):
        original_fsync = os.fsync
        cases = (("new target", False), ("replacement", True))

        for label, force in cases:
            with self.subTest(case=label):
                target = self.root / label.replace(" ", "-") / "file.txt"
                target.parent.mkdir(parents=True)
                if force:
                    target.write_bytes(b"old-content")
                directory_syncs = []

                def track_fsync(descriptor):
                    descriptor_stat = os.fstat(descriptor)
                    if stat.S_ISDIR(descriptor_stat.st_mode):
                        directory_syncs.append(descriptor)
                        return None
                    return original_fsync(descriptor)

                with mock.patch("install.os.fsync", side_effect=track_fsync):
                    installer.publish(
                        [installer.ManagedFile(target, b"new-content", 0o600)],
                        force=force,
                    )

                self.assertGreaterEqual(len(directory_syncs), 1)
                self.assertEqual(b"new-content", target.read_bytes())

    def test_unsupported_directory_fsync_does_not_fail_publication(self):
        self.target.parent.mkdir(parents=True)
        original_fsync = os.fsync

        def reject_directory_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(errno.EINVAL, "directory fsync unsupported")
            return original_fsync(descriptor)

        with mock.patch("install.os.fsync", side_effect=reject_directory_fsync):
            try:
                installer.publish([self.item()])
            except installer.InstallError as exc:
                self.fail("unsupported directory fsync failed publication: %s" % exc)

        self.assertEqual(b"new-content", self.target.read_bytes())

    def test_atomic_failure_reports_recoverable_restricted_temporary_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        with mock.patch("install.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(installer.InstallError, "unable to install") as caught:
                installer.publish([self.item()], force=True)

        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        temporary = temporary_files[0]
        self.assertIn("replace failed", str(caught.exception))
        self.assertIn("temporary file retained for recovery", str(caught.exception))
        self.assertIn(str(temporary), str(caught.exception))
        self.assertEqual(0o600, stat.S_IMODE(temporary.stat().st_mode))
        self.assertEqual(b"old-content", self.target.read_bytes())

    def test_failed_publication_restricts_recovery_file_for_public_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        with mock.patch("install.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(
                installer.InstallError,
                "temporary file retained for recovery",
            ):
                installer.publish([self.item(mode=0o755)], force=True)

        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertEqual(0o600, stat.S_IMODE(temporary_files[0].stat().st_mode))

    def test_publish_reports_real_recovery_after_parent_is_renamed(self):
        moved_parent = self.root / "moved-parent"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")
        captured = {}

        def rename_parent_then_fail(source, target, *args, **kwargs):
            temporary_name = Path(source).name
            captured["temporary_name"] = temporary_name
            self.target.parent.rename(moved_parent)
            self.target.parent.mkdir()
            false_recovery = self.target.parent / temporary_name
            false_recovery.write_bytes(b"unrelated")
            raise OSError("replace failed after parent rename")

        with mock.patch("install.os.replace", side_effect=rename_parent_then_fail):
            with self.assertRaisesRegex(
                installer.InstallError,
                "temporary file retained for recovery",
            ) as caught:
                installer.publish([self.item()], force=True)

        temporary_name = captured["temporary_name"]
        real_recovery = moved_parent / temporary_name
        false_recovery = self.target.parent / temporary_name
        diagnostic = str(caught.exception)
        self.assertEqual(b"new-content", real_recovery.read_bytes())
        self.assertEqual(b"unrelated", false_recovery.read_bytes())
        self.assertNotIn(str(false_recovery), diagnostic)
        self.assertTrue(
            str(real_recovery) in diagnostic
            or "no safe recovery pathname is available" in diagnostic
        )

    def test_mkdir_failure_is_normalized_to_install_error(self):
        with mock.patch("install.os.mkdir", side_effect=OSError("mkdir denied")):
            with self.assertRaisesRegex(installer.InstallError, "unable to install"):
                installer.publish([self.item()])

    def test_temporary_creation_failure_is_normalized_to_install_error(self):
        self.target.parent.mkdir(parents=True)

        with mock.patch(
            "install._create_temporary",
            side_effect=OSError("temporary creation denied"),
        ):
            with self.assertRaisesRegex(installer.InstallError, "unable to install"):
                installer.publish([self.item()])

    def test_temporary_fstat_failure_retries_identity_and_retains_recovery_file(self):
        self.target.parent.mkdir(parents=True)
        original_fstat = os.fstat
        failed = False

        def fail_first_file_fstat(descriptor):
            nonlocal failed
            result = original_fstat(descriptor)
            if stat.S_ISREG(result.st_mode) and not failed:
                failed = True
                raise OSError("temporary fstat failed")
            return result

        with mock.patch("install.os.fstat", side_effect=fail_first_file_fstat):
            with self.assertRaisesRegex(installer.InstallError, "unable to install"):
                installer.publish([self.item()])

        self.assertTrue(failed)
        self.assertFalse(self.target.exists())
        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertEqual(0o600, stat.S_IMODE(temporary_files[0].stat().st_mode))

    def test_persistent_temporary_fstat_failure_reports_recovery_candidate(self):
        self.target.parent.mkdir(parents=True)
        original_fstat = os.fstat

        def fail_file_fstat(descriptor):
            result = original_fstat(descriptor)
            if stat.S_ISREG(result.st_mode):
                raise OSError("temporary fstat unavailable")
            return result

        with mock.patch("install.os.fstat", side_effect=fail_file_fstat):
            with self.assertRaisesRegex(
                installer.InstallError,
                "temporary file identity could not be verified",
            ) as caught:
                installer.publish([self.item()])

        temporary_files = list(self.target.parent.glob(".feishu-connector-*"))
        self.assertEqual(1, len(temporary_files))
        self.assertEqual(0o600, stat.S_IMODE(temporary_files[0].stat().st_mode))
        self.assertIn(str(temporary_files[0]), str(caught.exception))
        self.assertFalse(self.target.exists())


class InstallerIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
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

    def test_installed_adapter_propagates_stdio_arguments_and_exit_code(self):
        installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)
        installed_cli = self.layout.scripts_dir / "feishu_notify.py"
        installed_cli.write_text(
            "import json, sys\n"
            "print(json.dumps(sys.argv[1:]))\n"
            "print('probe stderr', file=sys.stderr)\n"
            "raise SystemExit(17)\n",
            encoding="utf-8",
        )
        message = '"quoted"\n$(not-a-command) `not-a-command` --leading'

        result = subprocess.run(
            [str(self.layout.bin_dir / "feishu-notify-adapter")],
            input=json.dumps({"flow": "send", "message": message}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(17, result.returncode)
        self.assertEqual(
            ["send", "--message=%s" % message],
            json.loads(result.stdout),
        )
        self.assertEqual("probe stderr\n", result.stderr)

    def test_full_install_is_idempotent(self):
        first = installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)
        first_state = {
            path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for path in first
        }

        second = installer.install_connector(CONNECTOR_ROOT, self.layout, force=False)

        self.assertEqual(first, second)
        self.assertEqual(
            first_state,
            {
                path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for path in second
            },
        )

    def test_full_install_preserves_existing_config_sentinel(self):
        config = self.home / ".config" / "feishu-connector" / "config.json"
        config.parent.mkdir(parents=True)
        sentinel = b'{"sentinel": "user-owned"}\n'
        config.write_bytes(sentinel)
        config.chmod(0o600)

        installer.install_connector(CONNECTOR_ROOT, self.layout, force=True)

        self.assertEqual(sentinel, config.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(config.stat().st_mode))

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

    def test_invalid_home_and_codex_home_return_concise_install_error(self):
        cases = (
            ("HOME", "\x00invalid-home", {"PATH": ""}),
            (
                "CODEX_HOME",
                str(self.home),
                {"CODEX_HOME": "\x00invalid-codex-home", "PATH": ""},
            ),
        )
        for label, home, environ in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                stderr = io.StringIO()

                code = installer.main(
                    argv=[],
                    environ=environ,
                    home=home,
                    connector_root=CONNECTOR_ROOT,
                    stdout=stdout,
                    stderr=stderr,
                )

                self.assertEqual(1, code)
                self.assertEqual("", stdout.getvalue())
                self.assertTrue(
                    stderr.getvalue().startswith("Feishu connector installation error:")
                )
                self.assertIn(label, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertFalse((self.home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
