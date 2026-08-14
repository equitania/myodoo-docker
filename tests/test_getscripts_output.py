"""
Tests for the lean console output of getScripts.py.

Standard library only, like the rest of the suite. `requests` is imported at
module level by the script but none of the functions under test touch it, so a
placeholder module stands in when it is absent (customer servers and CI have
the real one).

HOME is redirected around the import: getScripts.py opens its log file at
import time, and a test run must not append to the operator's real
~/getscripts.log. It is put back immediately afterwards - the paths the script
derives from it are already captured, and leaving a rewritten HOME behind would
reach the other test modules that share this process.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_output -v
"""

import io
import logging
import os
import sys
import tempfile
import types
import unittest

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

LOG_FILE = gs._log_file


def read_log():
    with open(LOG_FILE, encoding="utf8") as handle:
        return handle.read()


class ConsoleOutputTestCase(unittest.TestCase):
    """Captures whatever the console handler writes during a test."""

    def setUp(self):
        self.console = io.StringIO()
        self.original_stream = gs._console_handler.stream
        gs._console_handler.stream = self.console
        gs._sudo_capture_ok = None
        self.addCleanup(self.restore)
        gs.set_verbosity()

    def restore(self):
        gs._console_handler.stream = self.original_stream
        gs.set_verbosity()
        gs._sudo_capture_ok = None

    @property
    def shown(self):
        return self.console.getvalue()


class LevelsTest(ConsoleOutputTestCase):
    def test_lean_mode_keeps_status_warnings_and_errors(self):
        gs.status("DNS optimization completed")
        gs.logger.warning("something looks off")
        gs.logger.error("something broke")

        self.assertIn("DNS optimization completed", self.shown)
        self.assertIn("WARNING: something looks off", self.shown)
        self.assertIn("ERROR: something broke", self.shown)

    def test_lean_mode_drops_info_from_the_console_but_not_from_the_log(self):
        gs.logger.info("a detail nobody asked for")

        self.assertNotIn("a detail nobody asked for", self.shown)
        self.assertIn("a detail nobody asked for", read_log())

    def test_verbose_mode_shows_info(self):
        gs.set_verbosity(verbose=True)
        gs.logger.info("a detail somebody asked for")

        self.assertIn("a detail somebody asked for", self.shown)

    def test_debug_implies_verbose(self):
        gs.set_verbosity(debug=True)
        self.assertTrue(gs.VERBOSE)
        self.assertEqual(gs._console_handler.level, logging.DEBUG)

    def test_status_lines_carry_no_level_prefix(self):
        gs.status("plain line")
        self.assertIn("plain line", self.shown)
        self.assertNotIn("STATUS:", self.shown)

    def test_leading_blank_lines_stay_in_front_of_the_marker(self):
        gs.logger.warning("\n\nspaced out")
        self.assertIn("\n\nWARNING: spaced out", self.shown)


class RunCommandOutputTest(ConsoleOutputTestCase):
    def test_lean_mode_swallows_a_successful_command(self):
        result = gs.run_command("echo unwanted-chatter")

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("unwanted-chatter", self.shown)
        self.assertIn("unwanted-chatter", read_log())

    def test_a_failure_puts_the_output_back_on_screen(self):
        result = gs.run_command("sh -c 'echo why-it-failed 1>&2; exit 3'")

        self.assertEqual(result.returncode, 3)
        self.assertIn("why-it-failed", self.shown)
        self.assertIn("exit code: 3", self.shown)

    def test_verbose_mode_does_not_capture(self):
        gs.set_verbosity(verbose=True)
        result = gs.run_command("echo streamed-live")

        # Nothing captured means the child wrote to the terminal itself, which
        # is the whole point of -v.
        self.assertIsNone(result.stdout)

    def test_interactive_commands_are_never_swallowed(self):
        result = gs.run_command("echo prompt-goes-here", interactive=True)

        self.assertIsNone(result.stdout)

    def test_an_explicit_capture_still_returns_the_output(self):
        result = gs.run_command("echo wanted", capture_output=True)

        self.assertIn(b"wanted", result.stdout)

    def test_sudo_is_streamed_when_no_passwordless_sudo_is_available(self):
        gs._sudo_capture_ok = False
        self.assertFalse(gs._may_capture("sudo apt update"))
        self.assertTrue(gs._may_capture("apt update"))

    def test_sudo_may_be_swallowed_when_it_cannot_prompt(self):
        gs._sudo_capture_ok = True
        self.assertTrue(gs._may_capture("sudo apt update"))


class ExcerptTest(unittest.TestCase):
    def test_a_long_output_is_capped_and_points_at_the_log(self):
        result = types.SimpleNamespace(
            stdout="\n".join(f"line {i}" for i in range(100)).encode(),
            stderr=b"",
        )
        excerpt = gs._child_output_excerpt(result)
        lines = excerpt.splitlines()

        self.assertEqual(len(lines), gs.CHILD_OUTPUT_EXCERPT_LINES + 1)
        self.assertIn("earlier line(s)", lines[0])
        self.assertIn(gs._log_file, lines[0])
        self.assertEqual(lines[-1], "line 99")

    def test_an_empty_output_produces_no_excerpt(self):
        result = types.SimpleNamespace(stdout=b"", stderr=None)
        self.assertEqual(gs._child_output_excerpt(result), "")


class ConsoleWarmUpTest(unittest.TestCase):
    """`konsole` must be startable after ups, and say so when it is not.

    Every assertion here is a lesson from one server that reported a warm
    console cache and then refused to start it:

      1. the check ran `python3 -c pass`, which cannot fail
      2. its failures were logger calls, invisible under lean output
      3. a missing uv was skipped in silence
      4. and last, the subtlest: the warm-up REBUILT the console's command
         instead of running it, passing `python3` where the console passed
         `sys.executable`. Both lines look correct. Only one of them works,
         and the working one was the one under test.
    """

    def setUp(self):
        self.calls = []
        self.report = list(gs._install_report)
        gs._install_report.clear()
        self.addCleanup(lambda: (gs._install_report.clear(),
                                 gs._install_report.extend(self.report)))
        self.patch("is_uv_installed", lambda: True)
        self.patch("install_uv", lambda: False)

    def patch(self, name, replacement):
        original = getattr(gs, name)
        setattr(gs, name, replacement)
        self.addCleanup(setattr, gs, name, original)

    def subprocess_returning(self, returncode):
        def runner(command, **_kwargs):
            self.calls.append(command)
            return types.SimpleNamespace(returncode=returncode, stdout="",
                                         stderr="")
        self.patch("subprocess", types.SimpleNamespace(run=runner))

    def statuses(self):
        return {name: status for name, status, _detail in gs._install_report}

    def test_it_starts_the_console_rather_than_a_rebuilt_command(self):
        """The only check that cannot drift from what `konsole` does."""
        self.subprocess_returning(0)
        gs.warm_console_cache()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("--check", self.calls[0])
        self.assertTrue(self.calls[0][1].endswith("ownerp_console.py"),
                        self.calls[0])

    def test_a_successful_check_is_reported_as_ok(self):
        self.subprocess_returning(0)
        gs.warm_console_cache()
        self.assertEqual(self.statuses().get("console (konsole)"), "ok")

    def test_a_failing_check_reaches_the_install_report(self):
        """Not a logger call: under lean output that is invisible on screen."""
        self.subprocess_returning(1)
        gs.warm_console_cache()
        self.assertEqual(self.statuses().get("console (konsole)"), "failed")

    def test_a_missing_uv_is_installed_rather_than_skipped(self):
        installed = []
        self.patch("is_uv_installed", lambda: False)
        self.patch("install_uv", lambda: installed.append(True) or True)
        self.subprocess_returning(0)
        gs.warm_console_cache()
        self.assertEqual(installed, [True])
        self.assertEqual(self.statuses().get("console (konsole)"), "ok")

    def test_a_missing_uv_that_cannot_be_installed_is_reported(self):
        self.patch("is_uv_installed", lambda: False)
        self.patch("install_uv", lambda: False)
        self.subprocess_returning(0)
        gs.warm_console_cache()
        self.assertEqual(self.statuses().get("console (konsole)"), "failed")
        self.assertEqual(self.calls, [])

    def test_a_warm_up_that_raises_does_not_take_the_update_with_it(self):
        def boom(*_args, **_kwargs):
            raise OSError("no such thing")
        self.patch("subprocess", types.SimpleNamespace(run=boom))
        gs.warm_console_cache()
        self.assertEqual(self.statuses().get("console (konsole)"), "failed")

    def test_the_specs_are_read_from_the_console_rather_than_duplicated(self):
        """A pin that drifts here looks exactly like a successful warm-up."""
        specs = gs._console_dependencies()
        self.assertTrue(any(s.startswith("textual") for s in specs), specs)
        self.assertTrue(any(s.startswith("pyyaml") for s in specs), specs)


if __name__ == "__main__":
    unittest.main()
