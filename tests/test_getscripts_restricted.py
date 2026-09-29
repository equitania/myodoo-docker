"""
Tests for the restricted mode of getScripts.py (v9.27.0).

A customer wants the Fish environment without ever running this script as
root or through sudo. The restricted mode installs nothing system-wide, names
the Debian packages the administrator has to install, and sets up only what
lives in the user's own home. Nothing here touches the real system: package
probes, privileges, the terminal and every copy step are patched.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_restricted -v
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

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


class PackageAdviceTest(unittest.TestCase):
    def test_only_debian_archive_packages_are_named(self):
        # The customer allows the Debian archive and backports only - the
        # Fish project's own repository (fish 4.5+) is exactly what is excluded.
        names = [p for p, _ in gs.RESTRICTED_REQUIRED_PACKAGES] + \
                [p for p, _, _ in gs.RESTRICTED_OPTIONAL_PACKAGES]
        self.assertEqual(names, ["fish", "git", "ca-certificates",
                                 "starship", "zoxide", "fastfetch"])

    def test_missing_packages_split_into_required_and_optional(self):
        present = {"git", "zoxide"}
        with mock.patch.object(gs.shutil, "which",
                               side_effect=lambda c: f"/usr/bin/{c}" if c in present else None), \
             mock.patch.object(gs.os.path, "exists", return_value=True):
            required, optional = gs.restricted_missing_packages()
        self.assertEqual(required, ["fish"])
        self.assertEqual([p for p, _ in optional], ["starship", "fastfetch"])

    def test_admin_commands_keep_required_and_optional_apart(self):
        # One apt-get line per group: an optional package that is unavailable
        # must never make the required install fail.
        lines = gs.restricted_admin_commands(["fish", "git"], [("starship", "x")])
        self.assertEqual(lines, ["apt-get update", "apt-get upgrade",
                                 "apt-get install fish git",
                                 "apt-get install starship"])

    def test_advice_is_silent_when_nothing_is_missing(self):
        with mock.patch("builtins.print") as printed:
            gs.print_restricted_package_advice([], [])
        printed.assert_not_called()


class ChooseModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        marker = mock.patch.object(gs, "RESTRICTED_MARKER",
                                   os.path.join(self.tmp, ".getscripts_restricted"))
        marker.start()
        self.addCleanup(marker.stop)

    def _choose(self, explicit=False, euid=1000, sudo=False, tty=True, answer=""):
        with mock.patch.object(gs.os, "geteuid", return_value=euid), \
             mock.patch.object(gs, "is_root_or_has_sudo", return_value=sudo or euid == 0), \
             mock.patch.object(gs.sys.stdin, "isatty", return_value=tty), \
             mock.patch("builtins.input", return_value=answer) as asked, \
             mock.patch("builtins.print"):
            result = gs.choose_restricted_mode(explicit)
        return result, asked

    def test_root_runs_the_full_setup_even_with_the_flag(self):
        self.assertFalse(self._choose(explicit=True, euid=0)[0])

    def test_passwordless_sudo_runs_the_full_setup(self):
        result, asked = self._choose(sudo=True)
        self.assertFalse(result)
        asked.assert_not_called()

    def test_flag_skips_the_question(self):
        result, asked = self._choose(explicit=True)
        self.assertTrue(result)
        asked.assert_not_called()

    def test_marker_skips_the_question(self):
        open(gs.RESTRICTED_MARKER, "w").close()
        result, asked = self._choose()
        self.assertTrue(result)
        asked.assert_not_called()

    def test_enter_accepts(self):
        self.assertTrue(self._choose(answer="")[0])

    def test_no_stops_without_error(self):
        with self.assertRaises(SystemExit) as stop:
            self._choose(answer="n")
        self.assertEqual(stop.exception.code, 0)

    def test_no_terminal_stops_with_error_instead_of_guessing(self):
        with self.assertRaises(SystemExit) as stop:
            self._choose(tty=False)
        self.assertEqual(stop.exception.code, 1)


class RunRestrictedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [
            mock.patch.object(gs, "RESTRICTED_MARKER", os.path.join(self.tmp, "marker")),
            mock.patch.object(gs, "print_header"),
            mock.patch.object(gs, "ensure_proxy_environment"),
            mock.patch.object(gs, "self_update_and_reexec"),
            mock.patch.object(gs, "is_starship_installed", return_value=(False, None)),
            mock.patch.object(gs, "is_fastfetch_installed", return_value=(False, None)),
            mock.patch.object(gs, "_offer_restricted_shell_change"),
            mock.patch.object(gs.os.path, "expanduser", return_value=self.tmp),
            mock.patch("builtins.print"),
            mock.patch.object(gs, "logger"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.update = mock.patch.object(gs, "update_repository").start()
        self.copy = mock.patch.object(gs, "copy_fish_configuration", return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def _run(self, os_info=("debian", "13"), missing=([], []), fish="4.0.2"):
        with mock.patch.object(gs, "get_os_info", return_value=os_info), \
             mock.patch.object(gs, "restricted_missing_packages", return_value=missing), \
             mock.patch.object(gs, "is_fish_installed", return_value=(True, fish)):
            return gs.run_restricted_mode()

    def test_debian_13_with_fish_4_0_sets_up_the_fish_environment(self):
        self.assertEqual(self._run(), 0)
        self.update.assert_called_once()
        self.copy.assert_called_once()
        self.assertTrue(os.path.exists(gs.RESTRICTED_MARKER))

    def test_missing_required_package_stops_before_the_repository(self):
        self.assertEqual(self._run(missing=(["git"], [])), 1)
        self.update.assert_not_called()

    def test_missing_optional_package_does_not_stop(self):
        self.assertEqual(self._run(missing=([], [("starship", "x")])), 0)

    def test_debian_12_is_refused_with_a_reason(self):
        # Fish 3.6 there, no Fish 4 in bookworm-backports.
        self.assertEqual(self._run(os_info=("debian", "12")), 1)
        self.update.assert_not_called()

    def test_fish_3_is_refused(self):
        self.assertEqual(self._run(fish="3.7.1"), 1)
        self.update.assert_not_called()

    def test_failed_clone_is_an_error_not_a_traceback(self):
        self.update.side_effect = gs.CommandError("git clone failed")
        self.assertEqual(self._run(), 1)
        self.copy.assert_not_called()


class WiringTest(unittest.TestCase):
    def test_decision_comes_before_every_root_step(self):
        source = read("getScripts.py")
        entry = source[source.index('if __name__ == "__main__":'):]
        decision = entry.index("choose_restricted_mode(")
        for root_step in ("run_first_time_setup()", "optimize_dns_configuration(",
                          "configure_proxy_settings()", "main()"):
            self.assertLess(decision, entry.index(root_step), root_step)

    def test_script_imports_without_requests(self):
        # On a minimal Debian python3-requests may be missing; the restricted
        # mode must still be able to say so instead of dying on the import.
        code = ("import sys; sys.modules['requests'] = None; "
                f"sys.path.insert(0, {REPO!r}); import getScripts; "
                "print(getScripts.requests)")
        env = dict(os.environ, HOME=tempfile.mkdtemp())
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")

    def test_ups_runs_without_sudo_in_restricted_mode(self):
        ups = read("fish", "functions", "linux", "ups.fish")
        branch = ups[ups.index(".getscripts_restricted"):ups.index("return")]
        self.assertIn("--restricted", branch)
        self.assertNotIn("sudo", branch)

    def test_restricted_mode_gets_its_own_panel(self):
        # The overview stays (the Captain missed it when it was switched off),
        # but it must not advertise server commands this user cannot run.
        prompt = read("fish", "conf.d", "50-prompt.fish")
        self.assertNotIn(".getscripts_restricted", prompt)
        help_fish = read("fish", "functions", "linux", "ownerp-help.fish")
        self.assertIn("test -e $HOME/.getscripts_restricted", help_fish)
        restricted = help_fish[help_fish.index("function __ownerp_help_restricted"):]
        for server_only in ("doup", "dobk", "konsole", "syspatch", "ngxset", "dps"):
            self.assertNotRegex(restricted, rf"__ownerp_help_row .*\b{server_only}\b")

if __name__ == "__main__":
    unittest.main()
