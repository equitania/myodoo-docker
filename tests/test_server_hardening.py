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


UFW_CONFIG = {
    "ufw": {
        "defaults": {"incoming": "deny", "outgoing": "allow", "routed": "deny"},
        "ipv6": True,
        "public_ports": [{"port": 80, "proto": "tcp", "comment": "HTTP"}],
        "restricted_ports": [{"port": 22, "proto": "tcp", "comment": "SSH",
                              "allowed_ips": [{"ip": "192.0.2.10", "comment": "Office A"}]}],
    }
}


class UfwOrderTest(unittest.TestCase):
    """For a few seconds on 28.09.2026 new SSH connections were refused:
    UFW was enabled before its allow rules existed."""

    def test_enable_comes_after_every_allow(self):
        calls = []

        def fake_run(cmd, check=False, timeout=30):
            calls.append(cmd)
            if cmd == "ufw status verbose":
                return "Status: inactive"
            if cmd == "cat /etc/default/ufw":
                return "IPV6=yes"
            return ""

        with mock.patch.object(sh, "run", side_effect=fake_run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/sbin/ufw"), \
             redirect_stdout(io.StringIO()):
            sh.audit_ufw(UFW_CONFIG, apply=True, force=True)

        enable = [i for i, c in enumerate(calls) if "ufw enable" in c]
        allows = [i for i, c in enumerate(calls) if c.startswith("ufw allow")]
        self.assertEqual(len(enable), 1)
        self.assertTrue(allows)
        self.assertGreater(enable[0], max(allows))

    def test_an_active_ufw_is_not_enabled_again(self):
        calls = []

        def fake_run(cmd, check=False, timeout=30):
            calls.append(cmd)
            if cmd == "ufw status verbose":
                return "Status: active"
            return "IPV6=yes" if cmd == "cat /etc/default/ufw" else ""

        with mock.patch.object(sh, "run", side_effect=fake_run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/sbin/ufw"), \
             redirect_stdout(io.StringIO()):
            sh.audit_ufw(UFW_CONFIG, apply=True, force=True)
        self.assertFalse(any("ufw enable" in c for c in calls))


class ModuleOrderTest(unittest.TestCase):
    def test_typed_order_does_not_matter(self):
        self.assertEqual(sh.ordered_modules(["ssh", "ufw", "fail2ban"]),
                         ["ufw", "fail2ban", "ssh"])

    def test_no_selection_means_all_in_order(self):
        self.assertEqual(sh.ordered_modules(None), list(sh.MODULE_ORDER))

    def test_every_ordered_module_has_a_function(self):
        self.assertEqual(set(sh.module_functions()), set(sh.MODULE_ORDER))


if __name__ == "__main__":
    unittest.main()
