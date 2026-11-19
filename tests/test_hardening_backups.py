"""Backups of server_hardening.py stay out of directories read as a whole."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server_hardening.py")
_spec = importlib.util.spec_from_file_location("server_hardening", _PATH)
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)


class BackupLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_backup_path_keeps_the_original_path_below_the_root(self):
        target = sh.backup_path_for("/etc/apt/apt.conf.d/20auto-upgrades", "20261119_104944",
                                    root=self.root)
        self.assertEqual(target, self.root / "etc/apt/apt.conf.d/20auto-upgrades.backup_20261119_104944")

    def test_backup_file_never_writes_next_to_the_file(self):
        conf_dir = self.root / "conf.d"
        conf_dir.mkdir()
        live = conf_dir / "20auto-upgrades"
        live.write_text("old\n")
        backups = self.root / "backups"
        with mock.patch.object(sh, "BACKUP_ROOT", backups), mock.patch.object(sh, "info"):
            result = sh.backup_file(live)
        self.assertEqual(sorted(p.name for p in conf_dir.iterdir()), ["20auto-upgrades"])
        self.assertTrue(result.startswith(str(backups)))
        self.assertEqual(Path(result).read_text(), "old\n")

    def test_stray_backups_are_moved_and_nothing_else(self):
        conf_dir = self.root / "apt.conf.d"
        conf_dir.mkdir()
        (conf_dir / "20auto-upgrades").write_text("new\n")
        (conf_dir / "20auto-upgrades.backup_20261119_104944").write_text("old\n")
        (conf_dir / "99-hardening.backup_20261001_120000.conf").write_text("old\n")
        (conf_dir / "50unattended-upgrades.backup").write_text("someone else's\n")
        backups = self.root / "backups"
        with mock.patch.object(sh, "info"), mock.patch.object(sh, "warn"):
            moved = sh.relocate_stray_backups(dirs=(str(conf_dir),), root=backups)
        self.assertEqual(sorted(p.name for p in conf_dir.iterdir()),
                         ["20auto-upgrades", "50unattended-upgrades.backup"])
        self.assertEqual(len(moved), 2)
        for path in moved:
            self.assertTrue(path.startswith(str(backups)))
            self.assertEqual(Path(path).read_text(), "old\n")

    def test_missing_directory_is_skipped(self):
        with mock.patch.object(sh, "info"):
            self.assertEqual(sh.relocate_stray_backups(dirs=(str(self.root / "nope"),),
                                                       root=self.root / "b"), [])

    def test_the_five_include_directories_are_covered(self):
        for directory in ("/etc/apt/apt.conf.d", "/etc/sysctl.d", "/etc/modprobe.d",
                          "/etc/audit/rules.d", "/etc/systemd/system/docker.service.d"):
            self.assertIn(directory, sh.STRAY_BACKUP_DIRS)


if __name__ == "__main__":
    unittest.main()
