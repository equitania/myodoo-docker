"""
Tests for the network-hang protections in getScripts.py.

A proxy-only server can swallow a `git pull` completely: no error, no visible
credential prompt (output is captured), just silence - `ups` never returns.
These tests cover the fix: run_command() gaining a `timeout`/`env` parameter,
and update_repository() degrading instead of hanging when a pull stalls or
fails.

Standard library only, like the rest of the suite. See
test_getscripts_output.py for why HOME is redirected around the import and why
a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_network -v
"""

import io
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

LOG_FILE = gs._log_file


def read_log():
    with open(LOG_FILE, encoding="utf8") as handle:
        return handle.read()


class ConsoleOutputTestCase(unittest.TestCase):
    """Captures whatever the console handler writes during a test.

    Same pattern as test_getscripts_output.py's helper - duplicated rather
    than imported so each test module stays runnable on its own.
    """

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


class RunCommandTimeoutTest(ConsoleOutputTestCase):
    """run_command(timeout=...) must not be able to hang forever."""

    def test_a_stalled_command_is_killed_and_reported_as_124(self):
        result = gs.run_command("sleep 2", timeout=0.3, capture_output=True)

        self.assertEqual(result.returncode, 124)
        self.assertIn("timed out", self.shown)
        self.assertIn("sleep 2", self.shown)

    def test_check_true_raises_commanderror_on_timeout(self):
        with self.assertRaises(gs.CommandError):
            gs.run_command("sleep 2", timeout=0.3, check=True)

    def test_none_keeps_the_previous_unbounded_behaviour(self):
        # No timeout given: behaves exactly like before this change.
        result = gs.run_command("echo still-unbounded", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"still-unbounded", result.stdout)

    def test_a_command_that_finishes_in_time_is_unaffected(self):
        result = gs.run_command("echo fast-enough", timeout=5, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"fast-enough", result.stdout)


class RunCommandEnvTest(unittest.TestCase):
    """env=... merges over the current environment, it does not replace it."""

    def test_extra_env_reaches_the_child_alongside_the_existing_environment(self):
        result = gs.run_command(
            "env", capture_output=True, env={"GETSCRIPTS_TEST_MARKER": "present"}
        )
        output = result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout
        self.assertIn("GETSCRIPTS_TEST_MARKER=present", output)
        # PATH (or another pre-existing variable) must have survived the merge.
        self.assertIn("PATH=", output)

    def test_no_env_argument_leaves_the_environment_untouched(self):
        result = gs.run_command("env", capture_output=True)
        output = result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout
        self.assertNotIn("GETSCRIPTS_TEST_MARKER", output)


class GitNetworkHardeningTest(unittest.TestCase):
    """Every git command that touches a remote must be bounded and silent-prompt-safe."""

    def test_git_pull_carries_terminal_prompt_and_low_speed_guards(self):
        captured = {}

        def fake_run_command(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(gs, "run_command", side_effect=fake_run_command):
            gs._run_git_network("git pull", capture_output=True)

        self.assertIn("http.lowSpeedLimit=1000", captured["command"])
        self.assertIn("http.lowSpeedTime=30", captured["command"])
        self.assertTrue(captured["command"].startswith("git -c"))
        self.assertIn("pull", captured["command"])
        self.assertEqual(captured["kwargs"].get("env"), {"GIT_TERMINAL_PROMPT": "0"})
        self.assertEqual(captured["kwargs"].get("timeout"), gs.GIT_NETWORK_TIMEOUT)
        self.assertTrue(captured["kwargs"].get("capture_output"))


class UpdateRepositoryDegradationTest(unittest.TestCase):
    """A failed or timed-out pull must not take the whole run down with it."""

    def _run_with(self, pull_returncode, pull_stderr=b""):
        calls = []

        def fake_run_command(command, **kwargs):
            calls.append((command, kwargs))
            if command.strip().endswith("pull"):
                return types.SimpleNamespace(
                    returncode=pull_returncode, stdout=b"", stderr=pull_stderr
                )
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        statuses = []

        with mock.patch.object(gs, "run_command", side_effect=fake_run_command), \
             mock.patch.object(gs, "status", side_effect=lambda msg: statuses.append(msg)), \
             mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.chdir"), \
             mock.patch.object(gs.subprocess, "check_output", return_value="2026\n"):
            gs.update_repository("/fake/myodoo-docker", "2026")

        return calls, statuses

    def test_a_timed_out_pull_does_not_raise_and_warns_clearly(self):
        calls, statuses = self._run_with(pull_returncode=124, pull_stderr=b"stalled")

        pull_calls = [c for c in calls if c[0].strip().endswith("pull")]
        self.assertEqual(len(pull_calls), 1)

        joined = "\n".join(statuses)
        self.assertIn("git pull fehlgeschlagen", joined)
        self.assertIn(str(gs.GIT_NETWORK_TIMEOUT), joined)
        self.assertIn("Proxy prüfen", joined)

    def test_a_failed_pull_without_timeout_also_just_warns(self):
        calls, statuses = self._run_with(pull_returncode=1, pull_stderr=b"fatal: unable to access")

        joined = "\n".join(statuses)
        self.assertIn("git pull fehlgeschlagen", joined)
        self.assertIn("fatal: unable to access", joined)

    def test_a_successful_pull_reports_no_failure(self):
        calls, statuses = self._run_with(pull_returncode=0)
        joined = "\n".join(statuses)
        self.assertNotIn("fehlgeschlagen", joined)


if __name__ == "__main__":
    unittest.main()
