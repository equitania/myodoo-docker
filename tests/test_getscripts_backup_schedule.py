"""
Tests for getScripts.migrate_backup_schedule() (9.42.0, 19.11.2026).

The cron template now runs a full backup at 02:00 and a databases-only backup
at 14:00. setup-maintenance-cron.sh installs the file once per server, so `ups`
has to carry the change to existing servers - and must leave alone every 14:00
line an operator changed on purpose.

Standard library only. See test_getscripts_output.py for the import setup.
"""

import os
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "scripts", "myodoo-maintenance.cron")

OLD_BLOCK = (
    "# Backup twice daily (02:00 + 14:00) — RPO ~12h. Requires /root/container2backup.yaml.\n"
    "0 2  * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1\n"
    "0 14 * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1\n"
)
NEW_BLOCK = gs.NEW_BACKUP_COMMENT + (
    "\n0 2  * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1\n"
    "0 14 * * * root /root/container2backup.py --sql-only </dev/null >> /var/log/container2backup.log 2>&1\n"
)


def template_text():
    with open(TEMPLATE, encoding="utf-8") as handle:
        return handle.read()


def old_template_text():
    text = template_text()
    assert NEW_BLOCK in text, "template backup block changed - update NEW_BLOCK"
    return text.replace(NEW_BLOCK, OLD_BLOCK)


class MigrateTextTest(unittest.TestCase):
    def test_old_template_becomes_the_current_template(self):
        # Byte-identical, so the readiness check "cron up to date" is green
        # on a migrated server exactly as on a freshly installed one.
        self.assertEqual(gs.migrate_backup_schedule_text(old_template_text()), template_text())

    def test_custom_script_dir_is_kept(self):
        old = old_template_text().replace(" /root/container2backup.py", " /opt/ops/container2backup.py")
        new = gs.migrate_backup_schedule_text(old)
        self.assertIn("0 14 * * * root /opt/ops/container2backup.py --sql-only </dev/null", new)
        self.assertIn("0 2  * * * root /opt/ops/container2backup.py </dev/null", new)

    def test_parked_line_stays_parked(self):
        old = old_template_text().replace("0 14 * * * root", "#OWNERP-DISABLED# 0 14 * * * root")
        new = gs.migrate_backup_schedule_text(old)
        self.assertIn("#OWNERP-DISABLED# 0 14 * * * root /root/container2backup.py --sql-only", new)

    def test_operator_changes_are_left_alone(self):
        old = old_template_text()
        cases = {
            "rescheduled": old.replace("0 14 * * * root", "30 13 * * * root"),
            "extra option": old.replace("0 14 * * * root /root/container2backup.py <",
                                        "0 14 * * * root /root/container2backup.py --only-db x <"),
            "already migrated": template_text(),
            # Set back to a full 14:00 run after the migration: the new comment
            # is there, so the next ups must not rewrite it again.
            "reverted on purpose": template_text().replace(" --sql-only", ""),
            "no template comment": old.replace(gs.OLD_BACKUP_COMMENT, "# my own backup plan"),
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertIsNone(gs.migrate_backup_schedule_text(text))


class MigrateFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gs-backup-schedule-")
        self.cron = os.path.join(self.dir, "myodoo-maintenance")
        self.backups = os.path.join(self.dir, "backups")

    def write(self, text):
        with open(self.cron, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(self.cron, 0o644)

    def run_migration(self):
        with mock.patch.object(gs, "record_install") as record:
            gs.migrate_backup_schedule(self.cron, self.backups)
        return record

    def test_rewrites_backs_up_and_reports_once(self):
        self.write(old_template_text())
        record = self.run_migration()
        with open(self.cron, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), template_text())
        self.assertEqual(stat.S_IMODE(os.stat(self.cron).st_mode), 0o644)
        saved = os.listdir(self.backups)
        self.assertEqual(len(saved), 1)
        with open(os.path.join(self.backups, saved[0]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), old_template_text())
        record.assert_called_once()
        self.assertEqual(record.call_args[0][1], "updated")
        self.assertEqual([n for n in os.listdir(self.dir) if ".tmp_" in n], [])

        # The second ups finds nothing to do and says nothing.
        record = self.run_migration()
        record.assert_not_called()
        self.assertEqual(len(os.listdir(self.backups)), 1)

    def test_missing_cron_file_is_a_no_op(self):
        record = self.run_migration()
        record.assert_not_called()
        self.assertFalse(os.path.exists(self.backups))



class RestorePlaybookPatternTest(unittest.TestCase):
    """The test-restore playbooks take the newest live backup. Since the 14:00
    run is databases only, its archive (..._sql_only) must not be the one they
    pick - the test instance would come up without its filestore."""

    def test_generated_pattern_skips_sql_only_archives(self):
        import fnmatch
        import subprocess
        out = tempfile.mkdtemp(prefix="gs-playbooks-")
        generator = os.path.join(os.path.dirname(__file__), "..", "Dockerfiles", "playbooks", "generate.py")
        subprocess.run([sys.executable, generator, "--version", "18", "--out", out],
                       check=True, capture_output=True)
        with open(os.path.join(out, "neutral.yaml"), encoding="utf-8") as handle:
            line = next(l for l in handle if l.strip().startswith("pattern:"))
        pattern = line.split('"')[1]
        full = pattern.replace("????-??-??_??-??-??", "2026-11-19_02-00-02")
        self.assertTrue(fnmatch.fnmatch(full, pattern))
        sql_only = full.replace(".7z", "_sql_only.7z")
        self.assertFalse(fnmatch.fnmatch(sql_only, pattern))


if __name__ == "__main__":
    unittest.main()
