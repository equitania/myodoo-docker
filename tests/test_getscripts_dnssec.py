"""
Tests for ensure_resolved_dnssec_off() in getScripts.py (v9.30.0).

On 11.10.2026 the DNS root key changed. systemd 249 knew only the old one, so
every host whose drop-in said DNSSEC=allow-downgrade answered SERVFAIL for
every name. The writer now says DNSSEC=no; this pass corrects the drop-ins it
wrote before.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_dnssec -v
"""

import glob
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME

OLD_DROPIN = """\
[Resolve]
DNS=1.1.1.1 8.8.8.8 9.9.9.9
FallbackDNS=8.8.4.4 1.0.0.1
DNSOverTLS=opportunistic
DNSSEC=allow-downgrade
Cache=yes
CacheFromLocalhost=yes
"""


def _done(returncode=0):
    return subprocess.CompletedProcess("systemctl", returncode, b"", b"")


class EnsureResolvedDnssecOffTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "dns-optimization.conf")
        gs._install_report.clear()
        self.addCleanup(gs._install_report.clear)
        for target, value in (("geteuid", 0),):
            patcher = mock.patch.object(gs.os, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.run_command = mock.patch.object(gs, "run_command", return_value=_done()).start()
        self.addCleanup(mock.patch.stopall)

    def write(self, content):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def read(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def test_allow_downgrade_becomes_no_and_resolved_restarts(self):
        self.write(OLD_DROPIN)
        gs.ensure_resolved_dnssec_off(self.path)
        self.assertEqual(self.read(), OLD_DROPIN.replace("DNSSEC=allow-downgrade", "DNSSEC=no"))
        self.run_command.assert_called_once()
        self.assertIn("restart systemd-resolved", self.run_command.call_args[0][0])
        self.assertEqual(gs._install_report[0][1], "updated")

    def test_other_lines_are_kept_byte_for_byte(self):
        self.write(OLD_DROPIN)
        gs.ensure_resolved_dnssec_off(self.path)
        self.assertEqual(
            [l for l in self.read().splitlines() if not l.startswith("DNSSEC")],
            [l for l in OLD_DROPIN.splitlines() if not l.startswith("DNSSEC")])

    def test_a_backup_is_left_next_to_the_file(self):
        self.write(OLD_DROPIN)
        gs.ensure_resolved_dnssec_off(self.path)
        backups = glob.glob(self.path + ".bak_*")
        self.assertEqual(len(backups), 1)
        # resolved only reads *.conf, so the backup must not end in .conf
        self.assertFalse(backups[0].endswith(".conf"))
        with open(backups[0], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), OLD_DROPIN)

    def test_yes_is_corrected_too(self):
        self.write(OLD_DROPIN.replace("allow-downgrade", "yes"))
        gs.ensure_resolved_dnssec_off(self.path)
        self.assertIn("DNSSEC=no\n", self.read())

    def test_already_no_is_silent_and_untouched(self):
        content = OLD_DROPIN.replace("allow-downgrade", "no")
        self.write(content)
        gs.ensure_resolved_dnssec_off(self.path)
        self.assertEqual(self.read(), content)
        self.run_command.assert_not_called()
        self.assertEqual(gs._install_report, [])
        self.assertEqual(glob.glob(self.path + ".bak_*"), [])

    def test_missing_file_is_silent(self):
        gs.ensure_resolved_dnssec_off(self.path)
        self.run_command.assert_not_called()
        self.assertEqual(gs._install_report, [])

    def test_without_root_nothing_is_written_but_it_is_reported(self):
        self.write(OLD_DROPIN)
        with mock.patch.object(gs.os, "geteuid", return_value=1000):
            gs.ensure_resolved_dnssec_off(self.path)
        self.assertEqual(self.read(), OLD_DROPIN)
        self.assertEqual(gs._install_report[0][1], "skipped")

    def test_a_failed_restart_is_reported_with_the_command(self):
        self.write(OLD_DROPIN)
        self.run_command.return_value = _done(1)
        gs.ensure_resolved_dnssec_off(self.path)
        status, detail = gs._install_report[0][1:]
        self.assertEqual(status, "failed")
        self.assertIn("systemctl restart systemd-resolved", detail)

    def test_both_writers_use_the_constant(self):
        with open(os.path.join(REPO, "getScripts.py"), encoding="utf-8") as handle:
            source = handle.read()
        written = re.findall(r"^DNSSEC=.*$", source, re.MULTILINE)
        self.assertEqual(written, ["DNSSEC={RESOLVED_DNSSEC}"] * 2)
        self.assertEqual(gs.RESOLVED_DNSSEC, "no")

    def test_main_runs_it(self):
        with open(os.path.join(REPO, "getScripts.py"), encoding="utf-8") as handle:
            source = handle.read()
        main = source[source.index("def main()"):]
        self.assertIn("ensure_resolved_dnssec_off()", main)


if __name__ == "__main__":
    unittest.main()
