"""
Tests for the no-config recovery offer in getScripts.py (offer_noconfig_recovery,
_active_noconfig_jobs).

A server can end up with no legacy CSV AND no YAML configuration at all -
migrate_legacy_csv() already names that case on its own console output, but
can only report it (ownerp_migrate.py runs with --quiet and --from-docker is
opt-in on purpose, never automatic). offer_noconfig_recovery() closes that
loop for an operator sitting at the terminal, while staying silent everywhere
`ups` also runs unattended (cron, scripts, a piped run).

Standard library only, like the rest of the suite. See
test_getscripts_output.py for why HOME is redirected around the import and why
a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_noconfig -v
"""

import json
import os
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


def _jobs_json(container2backup=(), odoo_build_cache=()):
    """Build the --json payload ownerp_cron.py would print.

    Each argument is a tuple of bools, one per cron line for that script -
    container2backup legitimately runs twice a day from two lines.
    """
    jobs = []
    for active in container2backup:
        jobs.append({"script": "container2backup.py", "active": active})
    for active in odoo_build_cache:
        jobs.append({"script": "odoo_build_cache.py", "active": active})
    return json.dumps({"path": "/etc/cron.d/myodoo-maintenance",
                        "customised": False, "jobs": jobs})


class ActiveNoconfigJobsTest(unittest.TestCase):
    """_active_noconfig_jobs(): the read side, kept separate from the prompt."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-noconfig-")
        self.addCleanup(lambda: None)

    def _touch_cron_script(self):
        path = os.path.join(self.home, "ownerp_cron.py")
        open(path, "w").close()
        return path

    def test_missing_ownerp_cron_returns_none(self):
        # No file created in self.home.
        self.assertIsNone(gs._active_noconfig_jobs(self.home))

    def test_nonzero_exit_returns_none(self):
        self._touch_cron_script()
        fake = types.SimpleNamespace(returncode=2, stdout="")
        with mock.patch.object(gs.subprocess, "run", return_value=fake):
            self.assertIsNone(gs._active_noconfig_jobs(self.home))

    def test_unparseable_json_returns_none(self):
        self._touch_cron_script()
        fake = types.SimpleNamespace(returncode=0, stdout="not json")
        with mock.patch.object(gs.subprocess, "run", return_value=fake):
            self.assertIsNone(gs._active_noconfig_jobs(self.home))

    def test_a_timeout_or_any_other_exception_returns_none(self):
        self._touch_cron_script()
        with mock.patch.object(gs.subprocess, "run", side_effect=OSError("boom")):
            self.assertIsNone(gs._active_noconfig_jobs(self.home))

    def test_both_jobs_off(self):
        self._touch_cron_script()
        payload = _jobs_json(container2backup=(False, False), odoo_build_cache=(False,))
        fake = types.SimpleNamespace(returncode=0, stdout=payload)
        with mock.patch.object(gs.subprocess, "run", return_value=fake):
            result = gs._active_noconfig_jobs(self.home)
        self.assertEqual(result, {"container2backup": False, "odoo_build_cache": False})

    def test_one_of_two_backup_lines_active_counts_as_active(self):
        self._touch_cron_script()
        payload = _jobs_json(container2backup=(False, True), odoo_build_cache=(False,))
        fake = types.SimpleNamespace(returncode=0, stdout=payload)
        with mock.patch.object(gs.subprocess, "run", return_value=fake):
            result = gs._active_noconfig_jobs(self.home)
        self.assertEqual(result, {"container2backup": True, "odoo_build_cache": False})

    def test_both_jobs_active(self):
        self._touch_cron_script()
        payload = _jobs_json(container2backup=(True, True), odoo_build_cache=(True,))
        fake = types.SimpleNamespace(returncode=0, stdout=payload)
        with mock.patch.object(gs.subprocess, "run", return_value=fake):
            result = gs._active_noconfig_jobs(self.home)
        self.assertEqual(result, {"container2backup": True, "odoo_build_cache": True})


class OfferNoconfigRecoveryTest(unittest.TestCase):
    """offer_noconfig_recovery(): the gate, the TTY split, and the three choices."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-offer-")
        self.run_calls = []
        self.status_lines = []

        def fake_run_command(command, **kwargs):
            self.run_calls.append((command, kwargs))
            return types.SimpleNamespace(returncode=0)

        self._patches = [
            mock.patch.object(gs, "run_command", side_effect=fake_run_command),
            mock.patch.object(gs, "status", side_effect=lambda msg: self.status_lines.append(msg)),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _write(self, name):
        open(os.path.join(self.home, name), "w").close()

    def _tty(self, is_tty):
        return mock.patch.multiple(
            gs.sys, stdin=mock.Mock(isatty=mock.Mock(return_value=is_tty)),
            stdout=mock.Mock(isatty=mock.Mock(return_value=is_tty)),
        )

    def _run(self, active_jobs, inputs=None, is_tty=True):
        with mock.patch.object(gs, "_active_noconfig_jobs", return_value=active_jobs), \
             self._tty(is_tty), \
             mock.patch("builtins.input", side_effect=inputs or []):
            gs.offer_noconfig_recovery(self.home)

    # --- gating -------------------------------------------------------

    def test_both_configs_present_skips_everything(self):
        self._write("container2backup.yaml")
        self._write("docker2update.yaml")
        with mock.patch.object(gs, "_active_noconfig_jobs") as read_jobs:
            self._run({"container2backup": True, "odoo_build_cache": True})
            read_jobs.assert_not_called()
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.status_lines, [])

    def test_only_backup_yaml_present_skips(self):
        self._write("container2backup.yaml")
        with mock.patch.object(gs, "_active_noconfig_jobs") as read_jobs:
            self._run({"container2backup": True, "odoo_build_cache": True})
            read_jobs.assert_not_called()
        self.assertEqual(self.run_calls, [])

    def test_cron_tool_missing_or_unreadable_skips_silently(self):
        # active_jobs is None: ownerp_cron.py missing, or --json failed.
        self._run(active_jobs=None, is_tty=True)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.status_lines, [])

    def test_both_jobs_already_off_skips(self):
        self._run({"container2backup": False, "odoo_build_cache": False})
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.status_lines, [])

    # --- non-TTY --------------------------------------------------------

    def test_non_tty_prints_one_status_line_and_runs_nothing(self):
        self._run({"container2backup": True, "odoo_build_cache": False}, is_tty=False)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)
        self.assertIn("docron --disable container2backup", self.status_lines[0])
        self.assertIn("ownerp_migrate.py --from-docker", self.status_lines[0])

    # --- interactive: choice 1 ------------------------------------------

    def test_choice_1_runs_migrate_from_docker_interactively(self):
        self._run({"container2backup": True, "odoo_build_cache": False}, inputs=["1"])
        self.assertEqual(len(self.run_calls), 1)
        command, kwargs = self.run_calls[0]
        self.assertIn("ownerp_migrate.py", command)
        self.assertIn("--from-docker", command)
        self.assertTrue(kwargs.get("interactive"))

    # --- interactive: choice 2 -------------------------------------------

    def test_choice_2_confirmed_disables_both_jobs_interactively(self):
        self._run({"container2backup": True, "odoo_build_cache": True},
                   inputs=["2", "j"])
        self.assertEqual(len(self.run_calls), 2)
        for command, kwargs in self.run_calls:
            self.assertIn("ownerp_cron.py", command)
            self.assertIn("--disable", command)
            self.assertTrue(kwargs.get("interactive"))
        joined = " ".join(c for c, _ in self.run_calls)
        self.assertIn("--disable container2backup", joined)
        self.assertIn("--disable odoo_build_cache", joined)

    def test_choice_2_declined_runs_nothing_and_shows_hint(self):
        self._run({"container2backup": True, "odoo_build_cache": True},
                   inputs=["2", "n"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_choice_2_default_answer_declines(self):
        self._run({"container2backup": True, "odoo_build_cache": True},
                   inputs=["2", ""])
        self.assertEqual(self.run_calls, [])

    # --- interactive: choice 3 / default / EOF / Ctrl+C -------------------

    def test_choice_3_runs_nothing_and_shows_hint(self):
        self._run({"container2backup": True, "odoo_build_cache": False}, inputs=["3"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_empty_answer_defaults_to_3(self):
        self._run({"container2backup": True, "odoo_build_cache": False}, inputs=[""])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_eof_defaults_to_3(self):
        self._run({"container2backup": True, "odoo_build_cache": False}, inputs=EOFError())
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_keyboard_interrupt_defaults_to_3(self):
        def raise_it(*_a, **_kw):
            raise KeyboardInterrupt()
        with mock.patch.object(gs, "_active_noconfig_jobs",
                                return_value={"container2backup": True, "odoo_build_cache": False}), \
             self._tty(True), \
             mock.patch("builtins.input", side_effect=raise_it):
            gs.offer_noconfig_recovery(self.home)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    # --- interactive: invalid input ---------------------------------------

    def test_invalid_input_reprompts_up_to_three_times_then_defaults_to_3(self):
        self._run({"container2backup": True, "odoo_build_cache": False},
                   inputs=["x", "y", "z"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_invalid_input_then_valid_choice_is_honoured(self):
        self._run({"container2backup": True, "odoo_build_cache": False},
                   inputs=["x", "1"])
        self.assertEqual(len(self.run_calls), 1)
        self.assertIn("--from-docker", self.run_calls[0][0])


if __name__ == "__main__":
    unittest.main()
