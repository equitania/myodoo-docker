"""
Tests for getScripts.neutralise_legacy_root_crontab() (9.37.0, 09.11.2026).

`ups` must not only report root-crontab lines that duplicate the managed cron.d
jobs, it must fix them on EVERY run - the installer runs only once per server.
The work is setup-maintenance-cron.sh --neutralise-legacy; these tests pin the
getScripts side: when it runs, and what it reports.

Standard library only. See test_getscripts_output.py for the import setup.
"""

import os
import subprocess
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


def _completed(code=0, out=b""):
    return subprocess.CompletedProcess(["x"], code, out, b"")


class NeutraliseLegacyRootCrontabTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-legacy-cron-")
        self.script = os.path.join(self.home, "setup-maintenance-cron.sh")
        with open(self.script, "w") as handle:
            handle.write("#!/bin/bash\n")
        self.cron_file = os.path.join(self.home, "cron.d-file")
        with open(self.cron_file, "w") as handle:
            handle.write("# cron\n")
        patch_path = mock.patch.object(gs, "MAINTENANCE_CRON_PATH", self.cron_file)
        patch_path.start()
        self.addCleanup(patch_path.stop)

    def _run(self, result=None, crontab=True):
        records = []
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/crontab" if crontab else None), \
                mock.patch.object(gs, "run_command", return_value=result or _completed()) as run, \
                mock.patch.object(gs, "record_install", side_effect=lambda *a: records.append(a)):
            gs.neutralise_legacy_root_crontab(self.home)
        return run, records

    def test_runs_every_time_the_cron_file_exists_and_is_silent_when_clean(self):
        run, records = self._run()
        self.assertIn("--neutralise-legacy", run.call_args.args[0])
        self.assertEqual(records, [])

    def test_reports_moved_lines_and_backup(self):
        out = (b"moved container2backup.py: 0 2 * * * x\n"
               b"moved ssl-renew.sh: 0 0 * * * y\n"
               b"moved container2backup.py: 0 14 * * * x\n"
               b"backup /var/backups/myodoo-docker/crontab-root.20261109-120000\n")
        _, records = self._run(_completed(0, out))
        self.assertEqual(len(records), 1)
        name, status, detail = records[0]
        self.assertEqual(status, "updated")
        self.assertIn("3 legacy line(s) moved to cron.d", detail)
        self.assertIn("backup: /var/backups/myodoo-docker/crontab-root.20261109-120000", detail)

    def test_skipped_without_the_managed_cron_file(self):
        os.remove(self.cron_file)
        run, records = self._run()
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_skipped_without_crontab_or_script(self):
        run, _ = self._run(crontab=False)
        run.assert_not_called()
        os.remove(self.script)
        run, _ = self._run()
        run.assert_not_called()

    def test_failure_is_recorded_not_raised(self):
        _, records = self._run(_completed(1))
        self.assertEqual(records[0][:2], ("cron (legacy root crontab)", "failed"))

    def test_main_calls_it_after_ensure_maintenance_cron(self):
        import inspect
        source = inspect.getsource(gs.main)
        self.assertLess(source.index("ensure_maintenance_cron(_myhome)"),
                        source.index("neutralise_legacy_root_crontab(_myhome)"))


if __name__ == "__main__":
    unittest.main()
