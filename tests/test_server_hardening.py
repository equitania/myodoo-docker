"""
Tests for server_hardening.py.

Written for the first-setup walkthrough of 28.09.2026: every defect found on
that fresh server that lives in this script is pinned here. Nothing in this
file touches a real firewall, sshd or package manager — run() is replaced.

Run from the repository root:

    uv run --with pyyaml python -m unittest tests.test_server_hardening -v
"""

import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server_hardening.py")
_spec = importlib.util.spec_from_file_location("server_hardening", _PATH)
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)


class AptInstallTest(unittest.TestCase):
    """AIDE timed out after 30 s on a fresh VPS and finished in the background."""

    def test_install_uses_the_long_timeout_and_no_prompts(self):
        with mock.patch.object(sh, "run", return_value="") as fake:
            sh.apt_install("aide aide-common")
        command = fake.call_args.args[0]
        self.assertIn("DEBIAN_FRONTEND=noninteractive", command)
        self.assertIn("apt-get install -y -qq aide aide-common", command)
        self.assertEqual(fake.call_args.kwargs.get("timeout"), sh.APT_INSTALL_TIMEOUT)
        self.assertGreaterEqual(sh.APT_INSTALL_TIMEOUT, 600)

    def test_no_install_bypasses_the_helper(self):
        source = Path(_PATH).read_text(encoding="utf-8")
        body = source.split("def apt_install", 1)[1].split("\ndef ", 1)[1]
        rest = source.split("def apt_install", 1)[0] + body
        # The PyYAML hint in the import guard is a message, not a call.
        calls = [line for line in rest.splitlines()
                 if "apt-get install" in line and "run(" in line]
        self.assertEqual(calls, [])


class SshValueMatchTest(unittest.TestCase):
    """Debian writes `Subsystem sftp     /usr/lib/openssh/sftp-server`."""

    def test_runs_of_whitespace_are_equal(self):
        self.assertTrue(sh._ssh_value_matches(
            "sftp     /usr/lib/openssh/sftp-server",
            "sftp /usr/lib/openssh/sftp-server"))

    def test_case_is_ignored(self):
        self.assertTrue(sh._ssh_value_matches("Yes", "yes"))

    def test_a_different_value_still_differs(self):
        self.assertFalse(sh._ssh_value_matches("LANG LC_* COLORTERM", "LANG LC_*"))


if __name__ == "__main__":
    unittest.main()
