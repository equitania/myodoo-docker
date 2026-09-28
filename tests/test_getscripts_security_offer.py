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

    def test_render_env_never_activates_backup_credentials(self):
        # The real template, not a test fixture: BACKUP_ENCRYPTION_ENABLED=true
        # and a placeholder BACKUP_PASSWORD ship in it, and
        # container2backup.py's get_encryption_settings() reads the central
        # .env first. An ups-created .env that activated them verbatim would
        # encrypt every backup with a password sitting in public GitHub
        # history.
        template_path = os.path.join(os.path.dirname(__file__), "..", "scripts", ".env.example")
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()
        text = gs._render_env(template, 22, ["192.0.2.10"])
        for line in text.splitlines():
            self.assertFalse(line.startswith("BACKUP_ENCRYPTION_ENABLED="), line)
            self.assertFalse(line.startswith("BACKUP_PASSWORD="), line)
        self.assertIn("# BACKUP_ENCRYPTION_ENABLED=true", text)
        self.assertIn("SSH_PORT=22\n", text)
        self.assertIn("ALLOWED_IP_1=192.0.2.10\n", text)


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

    def test_peers_from_ss_with_state_column(self):
        out = ("ESTAB 0 0 192.0.2.5:22 192.0.2.10:51000\n"
               "ESTAB 0 0 [2001:db8::1]:22 [2001:db8::5]:51001\n")
        with mock.patch.object(gs.subprocess, "run", return_value=self.run_result(out)):
            self.assertEqual(gs._ssh_peers([22]), ["192.0.2.10", "2001:db8::5"])

    def test_ss_failure_is_none(self):
        with mock.patch.object(gs.subprocess, "run", side_effect=OSError("no ss")):
            self.assertIsNone(gs._ssh_peers([22]))

    def test_running_containers(self):
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(gs.subprocess, "run", return_value=self.run_result("")):
            self.assertEqual(gs._running_containers(), 0)


def _audit(*areas, error=None, env=None):
    return {"version": "1.9.0", "env": env or {"present": True}, "error": error,
            "areas": [{"check_id": c, "modules": m, "on_fail": "FAIL",
                       "status": s, "findings": []} for c, m, s in areas]}


class OfferTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-hardening-")
        open(os.path.join(self.home, "server_hardening.py"), "w").close()
        self.env_path = os.path.join(self.home, gs.HARDENING_ENV_RELATIVE)
        os.makedirs(os.path.dirname(self.env_path))
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=22\nALLOWED_IP_1=192.0.2.10\n")
        self.commands = []
        self.answers = []
        patches = [
            mock.patch.object(gs.sys.stdin, "isatty", return_value=True),
            mock.patch.object(gs.sys.stdout, "isatty", return_value=True),
            mock.patch.object(gs, "run_command",
                              side_effect=lambda c, **k: self.commands.append(c)
                              or types.SimpleNamespace(returncode=0)),
            mock.patch("builtins.input", side_effect=lambda _p="": self.answers.pop(0)),
            mock.patch("builtins.print"),
            mock.patch.object(gs, "status"),
            mock.patch.object(gs, "_ssh_listen_ports", return_value=[22]),
            mock.patch.object(gs, "_ssh_peers", return_value=["192.0.2.10"]),
            mock.patch.object(gs, "_ssh_socket_active", return_value=False),
            mock.patch.object(gs, "_running_containers", return_value=0),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def offer(self, audit):
        with mock.patch.object(gs, "_hardening_audit", return_value=audit):
            gs.offer_security_hardening(self.home)

    def applied(self):
        return [c.split(" -m ", 1)[1] for c in self.commands if " --apply " in c]

    def test_silent_without_a_terminal(self):
        with mock.patch.object(gs.sys.stdin, "isatty", return_value=False):
            self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(self.commands, [])

    def test_silent_when_everything_is_ok_or_muted(self):
        mutes = os.path.join(self.home, gs.STORAGE_DRIVER_MUTES_RELATIVE)
        with open(mutes, "w", encoding="utf-8") as handle:
            handle.write("hardening_firewall | 28.09.2026 | fw in front\n")
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail"),
                          ("hardening_ssh", ["ssh"], "ok")))
        self.assertEqual(self.commands, [])

    def test_fix_now_applies_harmless_then_guarded_then_aide(self):
        self.answers = ["1"]
        self.offer(_audit(("hardening_integrity", ["auditd", "aide"], "fail"),
                          ("hardening_firewall", ["ufw"], "fail"),
                          ("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["auditd sysctl", "ufw", "aide"])

    def test_a_blocked_gate_applies_nothing_guarded(self):
        self.answers = ["1"]
        with mock.patch.object(gs, "_ssh_peers", return_value=["198.51.100.7"]):
            self.offer(_audit(("hardening_firewall", ["ufw"], "fail"),
                              ("hardening_ssh", ["ssh"], "fail")))
        self.assertEqual(self.applied(), [])

    def test_port_change_is_never_applied(self):
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=16667\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["1"]
        self.offer(_audit(("hardening_ssh", ["ssh"], "fail")))
        self.assertEqual(self.applied(), [])

    def test_fail2ban_waits_for_a_pending_port_change(self):
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=16667\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["1"]
        self.offer(_audit(("hardening_fail2ban", ["fail2ban"], "fail"),
                          ("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["sysctl"])

    def test_docker_restart_only_without_containers(self):
        self.answers = ["1"]
        self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertIn("systemctl restart docker", self.commands)
        self.commands.clear()
        self.answers = ["1"]
        with mock.patch.object(gs, "_running_containers", return_value=3):
            self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertEqual(self.applied(), ["docker"])
        self.assertNotIn("systemctl restart docker", self.commands)

    def test_show_commands_applies_nothing(self):
        self.answers = ["2"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(self.commands, [])

    def test_mute_one_area_calls_ownerp_mute(self):
        open(os.path.join(self.home, "ownerp_mute.py"), "w").close()
        self.answers = ["4", "1", "Firmen-Firewall davor"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(len(self.commands), 1)
        self.assertIn("hardening_firewall --reason", self.commands[0])

    def test_missing_env_is_offered_with_the_session_ip(self):
        os.unlink(self.env_path)
        template = os.path.join(self.home, "myodoo-docker", "scripts", ".env.example")
        os.makedirs(os.path.dirname(template))
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=\nALLOWED_IP_1=\n")
        # create? yes, port: default, ip 1: default, ip 2: done; then "later"
        self.answers = ["", "", "", "", "3"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        values = gs._read_env_file(self.env_path)
        self.assertEqual(values["SSH_PORT"], "22")
        self.assertEqual(values["ALLOWED_IP_1"], "192.0.2.10")

    def test_legacy_env_is_used_without_a_creation_offer(self):
        # server_hardening.py and container2backup.py both fall back to
        # <home>/.env themselves; a new central .env would shadow it (and
        # whatever real BACKUP_PASSWORD it holds).
        os.unlink(self.env_path)
        legacy = os.path.join(self.home, ".env")
        with open(legacy, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=22\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["3"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertFalse(os.path.isfile(self.env_path))
        self.assertEqual(self.commands, [])

    def test_apply_reads_the_legacy_env_when_the_central_one_is_missing(self):
        os.unlink(self.env_path)
        legacy = os.path.join(self.home, ".env")
        with open(legacy, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=22\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["1"]
        self.offer(_audit(("hardening_ssh", ["ssh"], "fail")))
        self.assertEqual(self.applied(), ["ssh"])

    def test_ctrl_c_during_ip_entry_cancels_env_creation(self):
        os.unlink(self.env_path)
        template = os.path.join(self.home, "myodoo-docker", "scripts", ".env.example")
        os.makedirs(os.path.dirname(template))
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=\nALLOWED_IP_1=\nALLOWED_IP_2=\n")
        # create? yes, port: default, ip 1: explicit, ip 2: Ctrl-C, then "later"
        with mock.patch("builtins.input",
                        side_effect=["", "", "192.0.2.20", KeyboardInterrupt, "3"]):
            self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertFalse(os.path.isfile(self.env_path))
        self.assertEqual(self.commands, [])

    def test_fail2ban_waits_when_the_ssh_port_is_unreadable(self):
        self.answers = ["1"]
        with mock.patch.object(gs, "_ssh_listen_ports", return_value=[]):
            self.offer(_audit(("hardening_fail2ban", ["fail2ban"], "fail"),
                              ("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["sysctl"])

    def test_docker_restart_needs_a_successful_apply_too(self):
        self.answers = ["1"]
        with mock.patch.object(gs, "_running_containers", return_value=None):
            self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertNotIn("systemctl restart docker", self.commands)

        self.commands.clear()
        self.answers = ["1"]
        with mock.patch.object(gs, "run_command",
                               side_effect=lambda c, **k: self.commands.append(c)
                               or types.SimpleNamespace(returncode=1)):
            self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertNotIn("systemctl restart docker", self.commands)

    def test_ctrl_c_during_the_audit_skips_the_offer(self):
        with mock.patch.object(gs, "_hardening_audit", side_effect=KeyboardInterrupt):
            gs.offer_security_hardening(self.home)  # must not raise
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
