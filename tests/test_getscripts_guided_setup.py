"""
Tests for the guided first setup in getScripts.py (9.35.0, 27.10.2026).

After the fresh-server fixes of 9.34.0 the first run still ended in
confusion: the readiness report told the operator to install the maintenance
cron by hand, a host with Docker but no Odoo yet was treated as a lost
configuration, and the hardening offer refused the very port change the
operator had just asked for. This file pins the replacement: getScripts
installs the cron itself, knows the fresh state, asks one question and lets
server_hardening.py carry the port change as a transition.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:
    python3 -m unittest tests.test_getscripts_guided_setup -v
"""

import inspect
import io
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


def _completed(code=0, out=""):
    return subprocess.CompletedProcess(["x"], code, out, "")


class MaintenanceCronTest(unittest.TestCase):
    """getScripts installs /etc/cron.d/myodoo-maintenance itself."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-cron-")
        self.script = os.path.join(self.home, "setup-maintenance-cron.sh")
        with open(self.script, "w") as handle:
            handle.write("#!/bin/bash\n")
        self.cron_file = os.path.join(self.home, "cron.d-file")
        patch_path = mock.patch.object(gs, "MAINTENANCE_CRON_PATH", self.cron_file)
        patch_path.start()
        self.addCleanup(patch_path.stop)

    def _run(self, docker=True, rc=0):
        records = []
        with mock.patch.object(gs.shutil, "which",
                               side_effect=lambda n: "/usr/bin/docker" if (docker and n == "docker") else None), \
                mock.patch.object(gs, "run_command", return_value=_completed(rc)) as run, \
                mock.patch.object(gs, "record_install", side_effect=lambda *a: records.append(a)):
            gs.ensure_maintenance_cron(self.home)
        return run, records

    def test_silent_without_docker(self):
        run, records = self._run(docker=False)
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_silent_when_cron_file_exists(self):
        with open(self.cron_file, "w") as handle:
            handle.write("# cron\n")
        run, records = self._run()
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_silent_when_script_missing(self):
        os.remove(self.script)
        run, records = self._run()
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_runs_script_and_records_installed(self):
        run, records = self._run()
        command = run.call_args.args[0]
        self.assertIn("setup-maintenance-cron.sh", command)
        self.assertTrue(command.startswith("bash "), command)
        self.assertEqual(records[0][:2], ("maintenance cron", "installed"))

    def test_records_failed_with_rerun_hint(self):
        run, records = self._run(rc=1)
        self.assertEqual(records[0][:2], ("maintenance cron", "failed"))
        self.assertIn(self.script, records[0][2])


class MainOrderTest(unittest.TestCase):
    def test_cron_runs_after_install_packages_before_migrate(self):
        source = inspect.getsource(gs.main)
        packages = source.index("run_install_packages(package_info)")
        cron = source.index("ensure_maintenance_cron(_myhome)")
        migrate = source.index("migrate_legacy_csv(_myhome)")
        self.assertLess(packages, cron)
        self.assertLess(cron, migrate)


class FreshServerTest(unittest.TestCase):
    """Docker installed, zero containers, no YAML: a fresh server, not a lost one."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-fresh-")

    def _fresh(self, docker=True, containers=False, yaml=False):
        if yaml:
            with open(os.path.join(self.home, "docker2update.yaml"), "w") as handle:
                handle.write("defaults: {}\n")
        with mock.patch.object(gs.shutil, "which",
                               side_effect=lambda n: "/usr/bin/docker" if (docker and n == "docker") else None), \
                mock.patch.object(gs, "_any_containers", return_value=containers):
            return gs.is_fresh_server(self.home)

    def test_fresh_when_docker_zero_containers_no_yaml(self):
        self.assertTrue(self._fresh())

    def test_not_fresh_when_yaml_exists(self):
        self.assertFalse(self._fresh(yaml=True))

    def test_not_fresh_when_docker_unreadable(self):
        self.assertFalse(self._fresh(containers=None))

    def test_not_fresh_with_containers(self):
        self.assertFalse(self._fresh(containers=True))

    def test_not_fresh_without_docker(self):
        self.assertFalse(self._fresh(docker=False))

    def test_noconfig_offer_silent_on_fresh_server(self):
        out = io.StringIO()
        out.isatty = lambda: True
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(gs, "_any_containers", return_value=False), \
                mock.patch.object(gs, "_prompt", side_effect=AssertionError("must not prompt")), \
                mock.patch("sys.stdin", io.StringIO()), mock.patch("sys.stdout", out), \
                mock.patch.object(gs, "_active_noconfig_jobs", return_value={"container2backup": True}):
            gs.offer_noconfig_recovery(self.home)
        self.assertEqual(out.getvalue(), "")

    def test_main_prints_next_step_after_readiness(self):
        source = inspect.getsource(gs.main)
        readiness = source.index("print_readiness_report(_myhome)")
        fresh = source.index("is_fresh_server(_myhome)")
        done = source.index('"Script completed successfully!"')
        self.assertLess(readiness, fresh)
        self.assertLess(fresh, done)
        self.assertIn("Noch keine Odoo-Instanz. Nächster Schritt: wizup", source)


if __name__ == "__main__":
    unittest.main()
