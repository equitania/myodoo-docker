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
import io
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


class MainOrderTest(unittest.TestCase):
    """The checks run after the packages they need (PyYAML, python3-dotenv)."""

    def test_offers_run_after_install_packages(self):
        source = inspect.getsource(gs.main)
        install = source.index("install_packages(")
        for call in ("migrate_legacy_csv(", "offer_noconfig_recovery(",
                     "offer_storage_driver_mute(", "offer_security_hardening(",
                     "cleanup_legacy_files(_myhome, myodoo_docker)"):  # the call, not the comment mentioning it
            self.assertLess(install, source.index(call), call)
        self.assertLess(source.index("offer_security_hardening("),
                        source.index("print_install_report("))


class BootstrapOfferTest(unittest.TestCase):
    """A host without Docker is a fresh server: offer bootstrap.sh, run it on a yes."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.repo = os.path.join(self.home, "myodoo-docker")
        os.makedirs(os.path.join(self.repo, "scripts"))
        self.script = os.path.join(self.repo, "scripts", "bootstrap.sh")
        with open(self.script, "w") as handle:
            handle.write("#!/bin/bash\n")
        gs._install_report.clear()

    def offer(self, which, tty, answers=(), returncode=0):
        out = io.StringIO()            # swallow the prompt text, keep the TTY answer
        out.isatty = lambda: tty       # type: ignore[method-assign]
        with mock.patch.object(gs.shutil, "which", return_value=which), \
             mock.patch.object(gs.sys.stdin, "isatty", return_value=tty), \
             mock.patch("sys.stdout", out), \
             mock.patch("builtins.input", side_effect=list(answers)), \
             mock.patch.object(gs, "run_command") as run, \
             mock.patch.object(gs, "status") as st:
            run.return_value = subprocess.CompletedProcess("bash", returncode, "", "")
            gs.offer_bootstrap(self.home, self.repo)
        return run, st

    def report(self):
        return [(n, s) for n, s, _ in gs._install_report]

    def test_docker_present_is_silent(self):
        run, st = self.offer("/usr/bin/docker", True)
        run.assert_not_called()
        st.assert_not_called()

    def test_no_tty_prints_one_line_and_runs_nothing(self):
        run, st = self.offer(None, False)
        run.assert_not_called()
        self.assertEqual(st.call_count, 1)
        self.assertIn(self.script, st.call_args.args[0])

    def test_accepted_runs_bootstrap_with_recursion_guard(self):
        run, _ = self.offer(None, True, [""])
        self.assertEqual(run.call_args.args[0], f"bash {self.script}")
        self.assertTrue(run.call_args.kwargs["interactive"])
        self.assertEqual(run.call_args.kwargs["env"], {"RUN_GETSCRIPTS": "0"})
        self.assertNotIn("timeout", run.call_args.kwargs)
        self.assertIn(("bootstrap", "installed"), self.report())

    def test_failed_bootstrap_is_recorded_and_run_continues(self):
        self.offer(None, True, [""], returncode=100)     # must not raise
        entry = [e for e in gs._install_report if e[0] == "bootstrap"][0]
        self.assertEqual(entry[1], "failed")
        self.assertIn("100", entry[2])

    def test_declined_is_skipped_with_the_command(self):
        run, _ = self.offer(None, True, ["n"])
        run.assert_not_called()
        entry = [e for e in gs._install_report if e[0] == "bootstrap"][0]
        self.assertEqual(entry[1], "skipped")
        self.assertIn(self.script, entry[2])

    def test_missing_script_is_silent(self):
        os.remove(self.script)
        run, st = self.offer(None, True)
        run.assert_not_called()
        st.assert_not_called()

    def test_main_calls_it_before_fish_and_after_the_clone(self):
        source = inspect.getsource(gs.main)
        self.assertLess(source.index("update_repository("), source.index("offer_bootstrap("))
        self.assertLess(source.index("offer_bootstrap("), source.index("ensure_base_packages("))
        self.assertLess(source.index("offer_bootstrap("), source.index("install_fish_if_needed("))


class NoconfigDockerGuardTest(unittest.TestCase):
    def test_offer_returns_without_docker(self):
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs, "_active_noconfig_jobs") as jobs:
            gs.offer_noconfig_recovery(tempfile.mkdtemp())
        jobs.assert_not_called()


class NoiseTest(unittest.TestCase):
    """A missing bat or 7zz on a fresh host is the expected state, not an error."""

    def test_missing_bat_is_not_an_error(self):
        with mock.patch.object(gs, "probe_output", return_value=None), \
             self.assertLogs(gs.logger, level="DEBUG") as logs:
            self.assertIsNone(gs.get_bat_version())
            self.assertFalse(gs.check_bat_version())
        self.assertFalse([r.getMessage() for r in logs.records if r.levelno >= logging.WARNING])

    def test_missing_7zz_reported_once_at_info(self):
        gs._SEVEN_ZZ_MISSING_REPORTED = False
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs.os.path, "isfile", return_value=False), \
             self.assertLogs(gs.logger, level="DEBUG") as logs:
            for _ in range(3):
                self.assertFalse(gs.check_7zip_version())
        hits = [r for r in logs.records
                if "7zz" in r.getMessage() and "not found" in r.getMessage()]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].levelno, logging.INFO)

    def test_bat_older_than_upstream_is_info(self):
        source = inspect.getsource(gs.install_or_update_bat)
        self.assertNotIn('logger.warning(f"Installed bat', source)
        self.assertIn('logger.info(f"Installed bat', source)


if __name__ == "__main__":
    unittest.main()
