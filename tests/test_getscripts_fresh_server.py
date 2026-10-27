"""
Tests for getScripts.py on a fresh server (27.10.2026).

An empty Debian 13 host rolled out by the README one-liner ended with
"Script completed successfully!" and no usable result: Fish was installed but
not recognised (its version line is localised), every privileged command
assumed the `sudo` package, the hardening audit ran before python3-dotenv was
installed, and nothing recognised a server without Docker as fresh.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:
    python3 -m unittest tests.test_getscripts_fresh_server -v
"""

import inspect
import logging
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


class ProbeTest(unittest.TestCase):
    """Version probes run under the C locale and read any capitalisation."""

    def test_probe_sets_c_locale(self):
        with mock.patch.object(gs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["x"], 0, "fish, version 4.9.3", "")
            gs.probe_output(["fish", "--version"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANG"], "C")
        self.assertIn("PATH", env)

    def test_probe_missing_binary_is_none(self):
        with mock.patch.object(gs.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(gs.probe_output(["nope"]))

    def test_probe_nonzero_exit_is_empty_string(self):
        with mock.patch.object(gs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["x"], 1, "", "boom")
            self.assertEqual(gs.probe_output(["x"]), "")

    def test_fish_version_localised_capital_v(self):
        with mock.patch.object(gs, "probe_output", return_value="fish, Version 4.9.3"):
            self.assertEqual(gs.is_fish_installed(), (True, "4.9.3"))

    def test_fish_version_english(self):
        with mock.patch.object(gs, "probe_output", return_value="fish, version 4.9.3"):
            self.assertEqual(gs.is_fish_installed(), (True, "4.9.3"))

    def test_fish_missing(self):
        with mock.patch.object(gs, "probe_output", return_value=None):
            self.assertEqual(gs.is_fish_installed(), (False, None))

    def test_fish_install_without_version_is_recorded_as_failed(self):
        # Debian branch: apt "succeeds", the probe still finds nothing.
        gs._install_report.clear()
        with mock.patch.object(gs, "is_fish_installed", return_value=(False, None)), \
             mock.patch.object(gs, "is_root_or_has_sudo", return_value=True), \
             mock.patch.object(gs, "get_os_info", return_value=("debian", "13")), \
             mock.patch.object(gs, "cleanup_duplicate_fish_repo"), \
             mock.patch.object(gs, "is_fish_repo_configured", return_value=True), \
             mock.patch.object(gs, "is_fish_repo_key_present", return_value=True), \
             mock.patch.object(gs, "fix_apt_keyring_permissions"), \
             mock.patch.object(gs, "run_command"), \
             mock.patch.object(gs.os.path, "exists", return_value=False):
            self.assertEqual(gs.install_fish_if_needed(), (False, False))
        names = [(n, s) for n, s, _ in gs._install_report]
        self.assertIn(("fish", "failed"), names)

    def test_fish_install_success_is_recorded(self):
        gs._install_report.clear()
        with mock.patch.object(gs, "is_fish_installed",
                               side_effect=[(False, None), (True, "4.9.3")]), \
             mock.patch.object(gs, "is_root_or_has_sudo", return_value=True), \
             mock.patch.object(gs, "get_os_info", return_value=("debian", "13")), \
             mock.patch.object(gs, "cleanup_duplicate_fish_repo"), \
             mock.patch.object(gs, "is_fish_repo_configured", return_value=True), \
             mock.patch.object(gs, "is_fish_repo_key_present", return_value=True), \
             mock.patch.object(gs, "fix_apt_keyring_permissions"), \
             mock.patch.object(gs, "run_command"), \
             mock.patch.object(gs.os.path, "exists", return_value=False):
            self.assertEqual(gs.install_fish_if_needed(), (True, True))
        self.assertIn(("fish", "installed", "v4.9.3"), gs._install_report)


class SudoStripTest(unittest.TestCase):
    """As root the `sudo` word is dropped - a root-only Debian has no sudo package."""

    def test_root_strips_leading_and_chained_sudo(self):
        with mock.patch.object(gs.os, "geteuid", return_value=0):
            self.assertEqual(gs.strip_sudo_for_root("sudo apt update"), "apt update")
            self.assertEqual(gs.strip_sudo_for_root("curl -o k && sudo mv k /etc/k"),
                             "curl -o k && mv k /etc/k")
            self.assertEqual(gs.strip_sudo_for_root("a; sudo b | sudo c"), "a; b | c")
            self.assertEqual(gs.strip_sudo_for_root('echo "sudo x"'), 'echo "sudo x"')

    def test_non_root_keeps_sudo(self):
        with mock.patch.object(gs.os, "geteuid", return_value=1000):
            self.assertEqual(gs.strip_sudo_for_root("sudo apt update"), "sudo apt update")

    def test_run_command_applies_stripping(self):
        with mock.patch.object(gs.os, "geteuid", return_value=0), \
             mock.patch.object(gs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["apt"], 0, b"", b"")
            gs.run_command("sudo apt update", capture_output=True)
        self.assertEqual(run.call_args.args[0], ["apt", "update"])


class WriteSystemFileTest(unittest.TestCase):
    def test_root_writes_directly(self):
        target = os.path.join(tempfile.mkdtemp(), "sub", "f.list")
        with mock.patch.object(gs.os, "geteuid", return_value=0), \
             mock.patch.object(gs.subprocess, "run") as run:
            gs.write_system_file(target, "deb x /\n")
        run.assert_not_called()
        self.assertEqual(open(target).read(), "deb x /\n")

    def test_root_appends(self):
        target = os.path.join(tempfile.mkdtemp(), "shells")
        open(target, "w").write("/bin/bash\n")
        with mock.patch.object(gs.os, "geteuid", return_value=0):
            gs.write_system_file(target, "/usr/bin/fish\n", append=True)
        self.assertEqual(open(target).read(), "/bin/bash\n/usr/bin/fish\n")

    def test_non_root_uses_sudo_tee(self):
        with mock.patch.object(gs.os, "geteuid", return_value=1000), \
             mock.patch.object(gs.subprocess, "run") as run:
            gs.write_system_file("/etc/x", "y", append=True)
        self.assertEqual(run.call_args.args[0], ["sudo", "tee", "-a", "/etc/x"])
        self.assertEqual(run.call_args.kwargs["input"], b"y")


class BasePackagesTest(unittest.TestCase):
    def test_installs_curl_when_missing(self):
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs, "install_system_package") as inst:
            gs.ensure_base_packages()
        self.assertEqual([c.args[0] for c in inst.call_args_list], ["curl", "ca-certificates"])

    def test_silent_when_curl_present(self):
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/curl"), \
             mock.patch.object(gs, "install_system_package") as inst:
            gs.ensure_base_packages()
        inst.assert_not_called()

    def test_main_installs_base_packages_before_fish(self):
        source = inspect.getsource(gs.main)
        self.assertLess(source.index("ensure_base_packages("), source.index("install_fish_if_needed("))


if __name__ == "__main__":
    unittest.main()
