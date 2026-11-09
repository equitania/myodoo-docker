"""
Tests for setup-maintenance-cron.sh --neutralise-legacy (1.4.0, 09.11.2026).

Incident 09.11.2026: root's personal crontab still held the pre-2026
container2backup/ssl-renew/cleanup-weblogs lines next to the managed
/etc/cron.d/myodoo-maintenance, so every backup ran twice at the same second.
The script now comments those lines out - after saving the crontab, never
deleting, never touching other lines.

A fake `crontab` on PATH stands in for the real one. Standard library only.
"""

import os
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(ROOT, "scripts", "setup-maintenance-cron.sh")

FAKE_CRONTAB = """#!/bin/sh
# usage: crontab -l -u root | crontab -u root -
store="$FAKE_CRONTAB_FILE"
case "$1" in
  -l) [ -f "$store" ] || { echo "no crontab for root" >&2; exit 1; }; cat "$store" ;;
  -u) cat > "$store" ;;
  *) exit 2 ;;
esac
"""

MANAGED = """\
0 2 * * * root /root/container2backup.py
0 0 * * * root /root/ssl-renew.sh
0 3 * * * root /root/cleanup-weblogs.py
# 30 4 * * * root /root/nightly-cleanup.sh
"""

LEGACY = """\
MAILTO=admin
# my note about container2backup
0 2 * * * (date; /root/container2backup.py) 2>&1 | tee -a /var/log/container2backup.log
0 0 * * * /root/ssl-renew.sh
30 4 * * * /root/nightly-cleanup.sh
15 5 * * * /usr/local/bin/unrelated-job.sh
"""


class NeutraliseLegacyCrontabTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        fake = os.path.join(bindir, "crontab")
        with open(fake, "w") as handle:
            handle.write(FAKE_CRONTAB)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.store = os.path.join(self.tmp.name, "root.crontab")
        self.cron_d = os.path.join(self.tmp.name, "myodoo-maintenance")
        self.backups = os.path.join(self.tmp.name, "backups")
        with open(self.cron_d, "w") as handle:
            handle.write(MANAGED)
        self.env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                        FAKE_CRONTAB_FILE=self.store, MAINTENANCE_CRON_DEST=self.cron_d,
                        CRONTAB_BACKUP_DIR=self.backups, SETUP_CRON_NO_SUDO="1")

    def run_script(self):
        return subprocess.run(["bash", SCRIPT, "--neutralise-legacy"], env=self.env,
                              capture_output=True, text=True)

    def write_store(self, text):
        with open(self.store, "w") as handle:
            handle.write(text)

    def read_store(self):
        with open(self.store) as handle:
            return handle.read()

    def test_comments_out_managed_jobs_only_and_saves_a_backup_first(self):
        self.write_store(LEGACY)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = "#OWNERP-MOVED-TO-CRON.D# "
        lines = self.read_store().splitlines()
        self.assertEqual(len(lines), len(LEGACY.splitlines()))          # nothing deleted
        self.assertEqual(lines[0], "MAILTO=admin")
        self.assertEqual(lines[1], "# my note about container2backup")
        self.assertTrue(lines[2].startswith(marker + "0 2 * * * (date; /root/container2backup.py)"))
        self.assertEqual(lines[3], marker + "0 0 * * * /root/ssl-renew.sh")
        # nightly-cleanup is parked in the managed file (commented): left alone
        self.assertEqual(lines[4], "30 4 * * * /root/nightly-cleanup.sh")
        self.assertEqual(lines[5], "15 5 * * * /usr/local/bin/unrelated-job.sh")
        saved = os.listdir(self.backups)
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].startswith("crontab-root."))
        with open(os.path.join(self.backups, saved[0])) as handle:
            self.assertEqual(handle.read(), LEGACY)
        self.assertEqual(result.stdout.count("moved "), 2)
        self.assertIn("moved container2backup.py:", result.stdout)
        self.assertIn(f"backup {self.backups}/crontab-root.", result.stdout)

    def test_second_run_is_silent_and_changes_nothing(self):
        self.write_store(LEGACY)
        self.run_script()
        after_first = self.read_store()
        result = self.run_script()
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.read_store(), after_first)
        self.assertEqual(len(os.listdir(self.backups)), 1)

    def test_no_crontab_does_nothing(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.backups))

    def test_unrelated_crontab_is_left_untouched_without_backup(self):
        text = "15 5 * * * /usr/local/bin/unrelated-job.sh\n"
        self.write_store(text)
        result = self.run_script()
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.read_store(), text)
        self.assertFalse(os.path.exists(self.backups))

    def test_nothing_happens_without_the_managed_cron_file(self):
        os.remove(self.cron_d)
        self.write_store(LEGACY)
        self.run_script()
        self.assertEqual(self.read_store(), LEGACY)

    def test_job_list_covers_the_readiness_check(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sr", os.path.join(ROOT, "scripts", "server-readiness.py"))
        sr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sr)
        with open(SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        for job in sr.MANAGED_JOBS:
            self.assertIn(job, text)
        self.assertIn(f"LEGACY_MARKER='{sr.LEGACY_CRON_MARKER}'", text)


if __name__ == "__main__":
    unittest.main()
