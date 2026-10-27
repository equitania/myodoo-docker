"""
Tests for the SSH access block of the first-run dialogue (27.10.2026).

The hardening .env used to be derived - port 22 and the address of the
current SSH session, confirmed with a default "J". The operator wanted to be
asked for a fixed port and a list of admin addresses at the first
installation. The block writes the .env right there; nothing here touches a
real sshd, ufw or the real home directory.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:
    python3 -m unittest tests.test_getscripts_firstrun_ssh -v
"""

import inspect
import io
import os
import stat
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


class ParseAddressesTest(unittest.TestCase):
    def test_commas_spaces_ipv6_and_mapped(self):
        ok, bad = gs.parse_admin_addresses("192.0.2.10, 198.51.100.7 2001:db8::1 ::ffff:192.0.2.11")
        self.assertEqual(ok, ["192.0.2.10", "198.51.100.7", "2001:db8::1", "192.0.2.11"])
        self.assertEqual(bad, [])

    def test_network_and_garbage_rejected_duplicates_dropped(self):
        ok, bad = gs.parse_admin_addresses("192.0.2.0/24, host, 192.0.2.1, 192.0.2.1")
        self.assertEqual(ok, ["192.0.2.1"])
        self.assertEqual(bad, ["192.0.2.0/24", "host"])

    def test_empty(self):
        self.assertEqual(gs.parse_admin_addresses("  "), ([], []))


class MinimalEnvTest(unittest.TestCase):
    def test_only_the_hardening_keys_are_active(self):
        text = gs.render_minimal_env(2222, ["192.0.2.10", "198.51.100.7"],
                                     "/root/myodoo-docker/scripts/.env.example")
        active = [l for l in text.splitlines() if l and not l.startswith("#")]
        self.assertEqual(active, ["SSH_PORT=2222", "ALLOWED_IP_1=192.0.2.10",
                                  "ALLOWED_IP_2=198.51.100.7"])
        self.assertIn("/root/myodoo-docker/scripts/.env.example", text)
        self.assertTrue(text.endswith("\n"))


class ConfigureSshAccessTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = os.path.join(self.home, gs.HARDENING_ENV_RELATIVE)
        self.ports = mock.patch.object(gs, "_ssh_listen_ports", return_value=[22])
        self.ports.start()
        self.peers = mock.patch.object(gs, "_ssh_peers", return_value=["203.0.113.5"])
        self.peers.start()

    def tearDown(self):
        self.ports.stop()
        self.peers.stop()

    def run_block(self, answers):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=list(answers)), \
             mock.patch("sys.stdout", out):
            result = gs.configure_ssh_access(self.home)
        return result, out.getvalue()

    def test_defaults_write_minimal_env_without_template(self):
        ok, out = self.run_block(["", "", ""])          # j, port 22, session peer
        self.assertTrue(ok)
        text = open(self.env).read()
        self.assertIn("SSH_PORT=22\n", text)
        self.assertIn("ALLOWED_IP_1=203.0.113.5\n", text)
        self.assertNotIn("sshd lauscht derzeit", out)
        self.assertIn(".env angelegt", out)
        self.assertEqual(stat.S_IMODE(os.stat(self.env).st_mode), 0o600)

    def test_other_port_prints_the_waiting_note(self):
        ok, out = self.run_block(["j", "2222", "192.0.2.10, 198.51.100.7"])
        self.assertTrue(ok)
        self.assertIn("sshd lauscht derzeit auf 22", out)
        self.assertIn("auf 2222 lauscht", out)
        text = open(self.env).read()
        self.assertIn("SSH_PORT=2222\n", text)
        self.assertIn("ALLOWED_IP_2=198.51.100.7\n", text)

    def test_template_is_rendered_when_present(self):
        tpl = os.path.join(self.home, "myodoo-docker", "scripts")
        os.makedirs(tpl)
        with open(os.path.join(tpl, ".env.example"), "w") as handle:
            handle.write("BACKUP_PASSWORD=x\nSSH_PORT=22\nALLOWED_IP_1=203.0.113.1\n")
        self.run_block(["", "", ""])
        text = open(self.env).read()
        self.assertIn("# BACKUP_PASSWORD=x", text)
        self.assertIn("ALLOWED_IP_1=203.0.113.5", text)
        self.assertNotIn("203.0.113.1", text)

    def test_network_rejected_then_accepted(self):
        ok, out = self.run_block(["", "", "192.0.2.0/24", "192.0.2.10"])
        self.assertTrue(ok)
        self.assertIn("'192.0.2.0/24' ist keine einzelne IP-Adresse", out)
        self.assertIn("ALLOWED_IP_1=192.0.2.10", open(self.env).read())

    def test_three_bad_attempts_write_nothing(self):
        ok, _ = self.run_block(["", "", "x", "y", "z"])
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.env))

    def test_invalid_port_twice_writes_nothing(self):
        ok, out = self.run_block(["", "99999", "abc"])
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.env))
        self.assertIn("Später", out)

    def test_decline_writes_nothing(self):
        ok, out = self.run_block(["n"])
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.env))
        self.assertIn("Später", out)

    def test_ctrl_c_writes_nothing(self):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt), \
             mock.patch("sys.stdout", out):
            self.assertFalse(gs.configure_ssh_access(self.home))
        self.assertFalse(os.path.exists(self.env))

    def test_no_peers_and_empty_answer_writes_nothing(self):
        self.peers.stop()
        with mock.patch.object(gs, "_ssh_peers", return_value=None):
            ok, out = self.run_block(["", "", ""])
        self.peers.start()
        self.assertFalse(ok)
        self.assertIn("Ohne Admin-IP keine .env", out)

    def test_existing_env_is_shown_not_rewritten(self):
        os.makedirs(os.path.dirname(self.env))
        with open(self.env, "w") as handle:
            handle.write("SSH_PORT=2200\nALLOWED_IP_1=192.0.2.9\n# ALLOWED_IP_2=\nALLOWED_IP_2=\n")
        ok, out = self.run_block([])
        self.assertFalse(ok)
        self.assertIn("SSH_PORT=2200", out)
        self.assertIn("192.0.2.9", out)
        self.assertIn("mcedit", out)

    def test_first_run_setup_calls_the_block(self):
        source = inspect.getsource(gs.run_first_time_setup)
        self.assertLess(source.index("configure_ssh_access("), source.index("mark_configured()"))


class ResolveHomeTest(unittest.TestCase):
    def test_sudo_su_targets_root(self):
        with mock.patch.dict(os.environ, {"SUDO_USER": "debian", "SUDO_COMMAND": "/usr/bin/su"}):
            self.assertEqual(gs.resolve_install_home(), os.path.expanduser("~"))

    def test_plain_root(self):
        env = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER", "SUDO_COMMAND")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(gs.resolve_install_home(), os.path.expanduser("~"))

    def test_setup_environment_uses_it(self):
        self.assertIn("resolve_install_home()", inspect.getsource(gs.setup_environment))

    def test_first_run_marker_follows_the_install_home(self):
        self.assertIn("resolve_install_home()", inspect.getsource(gs._first_run_marker))
        self.assertIn("_first_run_marker()", inspect.getsource(gs.is_first_run))
        self.assertIn("_first_run_marker()", inspect.getsource(gs.mark_configured))

    def test_legacy_marker_still_counts_as_configured(self):
        home = tempfile.mkdtemp()
        legacy = os.path.join(home, "legacy-marker")
        open(legacy, "w").write("x")
        with mock.patch.object(gs, "resolve_install_home", return_value=tempfile.mkdtemp()), \
             mock.patch.object(gs, "LEGACY_FIRST_RUN_MARKER", legacy):
            self.assertFalse(gs.is_first_run())


if __name__ == "__main__":
    unittest.main()
