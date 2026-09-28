"""
Tests for the security-hardening offer in getScripts.py.

On 28.09.2026 a freshly provisioned server passed bootstrap, getScripts and
the maintenance cron and was still wide open: UFW off, no .env, SSH on port 22
reachable from the internet. `ups` now offers the hardening — and must never
lock the operator out doing it. The gate is tested as a pure function; nothing
here touches a real firewall, sshd or Docker.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_security_offer -v
"""

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

TEMPLATE = """\
# comment
BACKUP_PASSWORD=
SSH_PORT=22
ALLOWED_IP_1=203.0.113.1
ALLOWED_IP_1_COMMENT=Example
ALLOWED_IP_2=203.0.113.2
ALLOWED_IP_2_COMMENT=
"""

ENV = {"SSH_PORT": "22", "ALLOWED_IP_1": "192.0.2.10", "ALLOWED_IP_2": "192.0.2.11"}


class EnvFileTest(unittest.TestCase):
    def test_read_env_tolerates_quotes_and_crlf(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env",
                                         newline="") as handle:
            handle.write('SSH_PORT = "16667"\r\n# x\r\nALLOWED_IP_1=\'192.0.2.10\'\r\n')
        self.addCleanup(os.unlink, handle.name)
        self.assertEqual(gs._read_env_file(handle.name),
                         {"SSH_PORT": "16667", "ALLOWED_IP_1": "192.0.2.10"})

    def test_allowed_ips_in_slot_order_with_gaps(self):
        self.assertEqual(gs._allowed_ips({"ALLOWED_IP_3": "192.0.2.3",
                                          "ALLOWED_IP_1": "192.0.2.1",
                                          "ALLOWED_IP_2": "",
                                          "ALLOWED_IP_1_COMMENT": "x"}),
                         ["192.0.2.1", "192.0.2.3"])

    def test_render_env_fills_port_and_ips(self):
        text = gs._render_env(TEMPLATE, 16667, ["192.0.2.10"])
        self.assertIn("SSH_PORT=16667\n", text)
        self.assertIn("ALLOWED_IP_1=192.0.2.10\n", text)
        self.assertIn("# comment\n", text)
        self.assertIn("BACKUP_PASSWORD=\n", text)

    def test_render_env_blanks_unused_template_ips(self):
        text = gs._render_env(TEMPLATE, 22, ["192.0.2.10"])
        self.assertNotIn("203.0.113", text)
        self.assertIn("ALLOWED_IP_2=\n", text)
        self.assertIn("ALLOWED_IP_1_COMMENT=\n", text)

    def test_render_env_appends_slots_the_template_lacks(self):
        text = gs._render_env("SSH_PORT=\n", 22, ["192.0.2.1", "192.0.2.2"])
        self.assertIn("ALLOWED_IP_2=192.0.2.2\n", text)

    def test_write_env_is_private_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cfg", ".env")
            self.assertTrue(gs._write_env(path, "SSH_PORT=22\n"))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
            self.assertFalse(gs._write_env(path, "SSH_PORT=99\n"))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "SSH_PORT=22\n")


class MutesTest(unittest.TestCase):
    def test_reads_every_muted_id(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, gs.STORAGE_DRIVER_MUTES_RELATIVE)
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# h\nhardening_firewall | 28.09.2026 | fw in front\n"
                             "docker_storage_driver | 15.09.2026 | kept\nbroken line\n")
            self.assertEqual(gs._muted_check_ids(home),
                             {"hardening_firewall", "docker_storage_driver"})
            self.assertTrue(gs._docker_storage_driver_muted(home))


class PeerHostTest(unittest.TestCase):
    def test_peer_host_forms(self):
        self.assertEqual(gs._peer_host("192.0.2.10:51234"), "192.0.2.10")
        self.assertEqual(gs._peer_host("[2001:db8::5]:51234"), "2001:db8::5")
        self.assertEqual(gs._peer_host("[::ffff:192.0.2.10]:51234"), "192.0.2.10")


class LockoutGateTest(unittest.TestCase):
    def test_clean_state_has_no_blockers(self):
        self.assertEqual(gs._lockout_blockers(ENV, [22], ["192.0.2.10"], False), [])

    def test_no_admin_ip_blocks(self):
        blockers = gs._lockout_blockers({"SSH_PORT": "22"}, [22], ["192.0.2.10"], False)
        self.assertTrue(any("ALLOWED_IP" in b for b in blockers))

    def test_a_session_outside_the_allowlist_blocks(self):
        blockers = gs._lockout_blockers(ENV, [22], ["192.0.2.10", "198.51.100.7"], False)
        self.assertTrue(any("außerhalb der Allowlist" in b for b in blockers))

    def test_unreadable_sessions_block(self):
        self.assertTrue(gs._lockout_blockers(ENV, [22], None, False))

    def test_port_change_blocks_and_is_detected(self):
        env = dict(ENV, SSH_PORT="16667")
        self.assertTrue(any("Portwechsel" in b
                            for b in gs._lockout_blockers(env, [22], ["192.0.2.10"], False)))
        self.assertTrue(gs._is_port_change(env, [22]))

    def test_gate_accepts_any_listening_port(self):
        env = dict(ENV, SSH_PORT="16667")
        self.assertEqual(gs._lockout_blockers(env, [22, 16667], ["192.0.2.10"], False), [])
        self.assertFalse(gs._is_port_change(env, [22, 16667]))

    def test_socket_activation_blocks(self):
        blockers = gs._lockout_blockers(ENV, [22], ["192.0.2.10"], True)
        self.assertTrue(any("ssh.socket" in b for b in blockers))


class SshFactsTest(unittest.TestCase):
    def run_result(self, stdout, code=0):
        return types.SimpleNamespace(returncode=code, stdout=stdout, stderr="")

    def test_listen_ports_from_sshd_t(self):
        with mock.patch.object(gs.subprocess, "run",
                               return_value=self.run_result("port 22\nport 16667\nx 1\n")):
            self.assertEqual(gs._ssh_listen_ports(), [22, 16667])

    def test_peers_from_ss(self):
        out = ("0 0 192.0.2.5:22 192.0.2.10:51000\n"
               "0 0 192.0.2.5:22 [::ffff:192.0.2.11]:51001\n")
        with mock.patch.object(gs.subprocess, "run", return_value=self.run_result(out)):
            self.assertEqual(gs._ssh_peers([22]), ["192.0.2.10", "192.0.2.11"])

    def test_ss_failure_is_none(self):
        with mock.patch.object(gs.subprocess, "run", side_effect=OSError("no ss")):
            self.assertIsNone(gs._ssh_peers([22]))

    def test_running_containers(self):
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(gs.subprocess, "run", return_value=self.run_result("")):
            self.assertEqual(gs._running_containers(), 0)


if __name__ == "__main__":
    unittest.main()
