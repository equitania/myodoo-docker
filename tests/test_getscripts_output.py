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


if __name__ == "__main__":
    unittest.main()
