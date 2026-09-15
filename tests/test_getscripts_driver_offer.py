"""
Tests for the storage-driver mute offer in getScripts.py
(offer_storage_driver_mute, _docker_storage_driver_muted).

server-readiness.py's check_docker_storage_driver() reports a permanent WARN
when Docker is not on overlay2. That is correct and, on a host that
deliberately keeps a different driver (a developers' terminal server that
never builds, a box nobody wants to restart), permanent noise. Mirrors
offer_noconfig_recovery() (see test_getscripts_noconfig.py): silent unless
every gate holds, one question per interactive run.

Standard library only, like the rest of the suite. See
test_getscripts_output.py for why HOME is redirected around the import and why
a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_driver_offer -v
"""

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


def _docker_info_result(returncode=0, driver="overlayfs"):
    return types.SimpleNamespace(returncode=returncode, stdout=f"{driver}\n", stderr="")


class DockerStorageDriverMutedTest(unittest.TestCase):
    """_docker_storage_driver_muted(): the read side, kept separate from the prompt."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-muted-")

    def _write_mutes(self, text):
        path = os.path.join(self.home, gs.STORAGE_DRIVER_MUTES_RELATIVE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_no_mutes_file_is_not_muted(self):
        self.assertFalse(gs._docker_storage_driver_muted(self.home))

    def test_muted_entry_is_detected(self):
        self._write_mutes("docker_storage_driver | 2026-09-15 | kept on purpose\n")
        self.assertTrue(gs._docker_storage_driver_muted(self.home))

    def test_other_entries_do_not_count(self):
        self._write_mutes("backup_config | 2026-09-15 | test server\n")
        self.assertFalse(gs._docker_storage_driver_muted(self.home))

    def test_comments_and_blank_lines_are_ignored(self):
        self._write_mutes("# header\n\n   \n# docker_storage_driver | not | a mute\n")
        self.assertFalse(gs._docker_storage_driver_muted(self.home))


class OfferStorageDriverMuteTest(unittest.TestCase):
    """offer_storage_driver_mute(): the gate, the TTY split, and the three choices."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-driveroffer-")
        self.run_calls = []
        self.status_lines = []
        self.stdout = []

        def fake_run_command(command, **kwargs):
            self.run_calls.append((command, kwargs))
            return types.SimpleNamespace(returncode=0)

        def fake_print(*args, **kwargs):
            self.stdout.append(" ".join(str(a) for a in args))

        self._patches = [
            mock.patch.object(gs, "run_command", side_effect=fake_run_command),
            mock.patch.object(gs, "status", side_effect=lambda msg: self.status_lines.append(msg)),
            mock.patch("builtins.print", side_effect=fake_print),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _write_mute_script(self):
        open(os.path.join(self.home, "ownerp_mute.py"), "w").close()

    def _tty(self, is_tty):
        return mock.patch.multiple(
            gs.sys, stdin=mock.Mock(isatty=mock.Mock(return_value=is_tty)),
            stdout=mock.Mock(isatty=mock.Mock(return_value=is_tty)),
        )

    def _run(self, docker_present=True, docker_info=None, muted=False,
              mute_script=True, is_tty=True, inputs=None):
        if mute_script:
            self._write_mute_script()
        if docker_info is None:
            docker_info = _docker_info_result()
        with mock.patch("shutil.which", return_value=("/usr/bin/docker" if docker_present else None)), \
             mock.patch.object(gs.subprocess, "run", return_value=docker_info), \
             mock.patch.object(gs, "_docker_storage_driver_muted", return_value=muted), \
             self._tty(is_tty), \
             mock.patch("builtins.input", side_effect=inputs or []):
            gs.offer_storage_driver_mute(self.home)

    # --- gating -----------------------------------------------------------

    def test_no_docker_skips_silently(self):
        self._run(docker_present=False)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.status_lines, [])
        self.assertEqual(self.stdout, [])

    def test_docker_info_failure_skips_silently(self):
        self._run(docker_info=_docker_info_result(returncode=1))
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_docker_info_exception_skips_silently(self):
        self._write_mute_script()
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
             mock.patch.object(gs.subprocess, "run", side_effect=OSError("timed out")), \
             self._tty(True):
            gs.offer_storage_driver_mute(self.home)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_overlay2_driver_skips_silently(self):
        self._run(docker_info=_docker_info_result(driver="overlay2"))
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_empty_driver_skips_silently(self):
        self._run(docker_info=_docker_info_result(driver=""))
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_already_muted_skips_silently(self):
        self._run(muted=True)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_mute_script_missing_skips_silently(self):
        self._run(mute_script=False)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.stdout, [])

    def test_non_tty_skips_silently_no_extra_line(self):
        self._run(is_tty=False)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.status_lines, [])
        self.assertEqual(self.stdout, [])

    # --- interactive: choice 1 --------------------------------------------

    def test_choice_1_prints_steps_and_runs_nothing(self):
        self._run(inputs=["1"])
        self.assertEqual(self.run_calls, [])
        joined = "\n".join(self.stdout)
        self.assertIn("daemon.json", joined)
        self.assertIn("overlay2", joined)
        self.assertIn("systemctl restart docker", joined)
        self.assertIn("reboot", joined)
        self.assertIn("doup", joined)

    def test_choice_1_never_suggests_overwriting_daemon_json(self):
        """On proxy-only hosts daemon.json carries the proxy and DNS; a copied
        one-liner that rewrites the file would take both away."""
        self._run(inputs=["1"])
        joined = "\n".join(self.stdout)
        self.assertNotIn("tee /etc/docker/daemon.json", joined)
        self.assertNotIn("> /etc/docker/daemon.json", joined)
        self.assertIn("daemon.json.bak", joined)

    def test_choice_1_merge_command_keeps_existing_keys(self):
        """Run the printed merge command against a temp copy: proxy and DNS
        survive, storage-driver is added."""
        import json
        import re
        import subprocess
        import sys
        import tempfile
        self._run(inputs=["1"])
        line = next(l for l in self.stdout if "python3 -c" in l)
        code = re.search(r"python3 -c '(.*)'\s*$", line).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daemon.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"proxies": {"http-proxy": "http://proxy.example.com:8080"},
                           "dns": ["192.0.2.53"]}, handle)
            subprocess.run([sys.executable, "-c",
                            code.replace("/etc/docker/daemon.json", path)],
                           check=True)
            with open(path, encoding="utf-8") as handle:
                result = json.load(handle)
        self.assertEqual(result["storage-driver"], "overlay2")
        self.assertEqual(result["proxies"]["http-proxy"], "http://proxy.example.com:8080")
        self.assertEqual(result["dns"], ["192.0.2.53"])

    # --- interactive: choice 2 ---------------------------------------------

    def test_choice_2_confirmed_mutes_with_interactive_true(self):
        self._run(docker_info=_docker_info_result(driver="overlayfs"),
                   inputs=["2", "j"])
        self.assertEqual(len(self.run_calls), 1)
        command, kwargs = self.run_calls[0]
        self.assertIn("ownerp_mute.py", command)
        self.assertIn("docker_storage_driver", command)
        self.assertIn("--reason", command)
        self.assertIn("overlayfs", command)
        self.assertTrue(kwargs.get("interactive"))
        self.assertTrue(kwargs.get("shell"))

    def test_choice_2_declined_runs_nothing_and_shows_hint(self):
        self._run(inputs=["2", "n"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_choice_2_default_answer_declines(self):
        self._run(inputs=["2", ""])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    # --- interactive: choice 3 / default / EOF / Ctrl+C ---------------------

    def test_choice_3_runs_nothing_and_shows_hint(self):
        self._run(inputs=["3"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)
        self.assertIn("ownerp_mute.py docker_storage_driver", self.status_lines[0])

    def test_empty_answer_defaults_to_3(self):
        self._run(inputs=[""])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_eof_defaults_to_3(self):
        self._run(inputs=EOFError())
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_keyboard_interrupt_defaults_to_3(self):
        def raise_it(*_a, **_kw):
            raise KeyboardInterrupt()
        self._write_mute_script()
        with mock.patch("shutil.which", return_value="/usr/bin/docker"), \
             mock.patch.object(gs.subprocess, "run", return_value=_docker_info_result()), \
             mock.patch.object(gs, "_docker_storage_driver_muted", return_value=False), \
             self._tty(True), \
             mock.patch("builtins.input", side_effect=raise_it):
            gs.offer_storage_driver_mute(self.home)
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    # --- interactive: invalid input -----------------------------------------

    def test_invalid_input_reprompts_up_to_three_times_then_defaults_to_3(self):
        self._run(inputs=["x", "y", "z"])
        self.assertEqual(self.run_calls, [])
        self.assertEqual(len(self.status_lines), 1)

    def test_invalid_input_then_valid_choice_is_honoured(self):
        self._run(inputs=["x", "2", "j"])
        self.assertEqual(len(self.run_calls), 1)
        self.assertIn("ownerp_mute.py", self.run_calls[0][0])


if __name__ == "__main__":
    unittest.main()
