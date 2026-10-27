"""
Tests for the SSH port transition in server_hardening.py (1.12.0).

A port change used to be "the six manual steps". Now sshd listens on the old
and the new port at the same time (a *transition*, recorded in a marker file
next to the .env), the firewall admits both, and the old port closes once a
login over the new one has been seen. Nothing here touches sshd, ufw or
systemd — run(), subprocess and the sshd_config path are replaced.

Run from the repository root:

    uv run --with pyyaml python -m unittest tests.test_server_hardening_transition -v
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server_hardening.py")
_spec = importlib.util.spec_from_file_location("server_hardening_t", _PATH)
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)

IPS = [{"n": 1, "ip": "198.51.100.7", "comment": "office"},
       {"n": 2, "ip": "203.0.113.5", "comment": ""}]


def _config(port=16667):
    return {
        "ufw": {"restricted_ports": [{"port": port, "proto": "any",
                                      "comment": "SSH Custom Port",
                                      "allowed_ips": [dict(a) for a in IPS]}],
                "public_ports": [{"port": 80, "proto": "tcp", "comment": "HTTP"}]},
        "fail2ban": {"jails": {"sshd": {"enabled": True, "port": port}}},
        "ssh": {"enabled": True, "port": port,
                "settings": {"PermitRootLogin": "yes"}},
        "auto_updates": {"enabled": True, "auto_reboot": True},
    }


class _TempCentral(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        central = Path(self.tmp.name) / "central"
        central.mkdir()
        self.central = central
        patcher = mock.patch.object(sh, "CENTRAL_DIR", central)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = mock.patch.object(sh, "TRANSITION_MARKER", central / "ssh-transition")
        patcher2.start()
        self.addCleanup(patcher2.stop)
        sh.Stats.reset()
        sh.Report.reset()


class MarkerTest(_TempCentral):
    def test_read_missing_marker_is_none(self):
        self.assertIsNone(sh.read_transition())

    def test_write_then_read_roundtrip(self):
        sh.write_transition(22, 16667)
        self.assertEqual(sh.read_transition(), (22, 16667))
        self.assertEqual(oct(sh.TRANSITION_MARKER.stat().st_mode & 0o777), "0o600")
        sh.clear_transition()
        self.assertIsNone(sh.read_transition())
        sh.clear_transition()  # idempotent

    def test_malformed_marker_is_none(self):
        sh.TRANSITION_MARKER.write_text("twenty-two\n")
        self.assertIsNone(sh.read_transition())
        sh.TRANSITION_MARKER.write_text("22\n")
        self.assertIsNone(sh.read_transition())


class RewritePortsTest(unittest.TestCase):
    def test_rewrite_replaces_single_port_with_two(self):
        out = sh._rewrite_ports("Include /etc/ssh/sshd_config.d/*.conf\nPort 22\nX11Forwarding no\n",
                                [22, 16667])
        self.assertEqual(out.splitlines(),
                         ["Include /etc/ssh/sshd_config.d/*.conf", "Port 22", "Port 16667",
                          "X11Forwarding no"])

    def test_rewrite_removes_commented_port_lines(self):
        out = sh._rewrite_ports("#Port 22\nPort 2200\n# Port 1\nMaxAuthTries 3\n", [16667])
        self.assertEqual(out.splitlines(), ["Port 16667", "MaxAuthTries 3"])

    def test_rewrite_appends_when_no_port_line(self):
        out = sh._rewrite_ports("MaxAuthTries 3\n", [16667])
        self.assertEqual(out.splitlines(), ["MaxAuthTries 3", "Port 16667"])

    def test_rewrite_keeps_other_directives_in_place(self):
        src = "A 1\nPort 22\nB 2\nPort 23\nC 3\n"
        out = sh._rewrite_ports(src, [22, 16667])
        self.assertEqual(out.splitlines(), ["A 1", "Port 22", "Port 16667", "B 2", "C 3"])


class ConfigPatchTest(unittest.TestCase):
    def test_patch_sets_jail_port_and_transitional_ufw_rule(self):
        cfg = _config()
        sh.apply_transition_to_config(cfg, (22, 16667), IPS)
        self.assertEqual(cfg["fail2ban"]["jails"]["sshd"]["port"], "22,16667")
        rules = cfg["ufw"]["restricted_ports"]
        self.assertEqual(len(rules), 2)
        extra = rules[1]
        self.assertEqual(extra["port"], 22)
        # proto any, like the SSH_PORT rule: audit_ufw's restricted-rule regex
        # matches "22  ALLOW IN  <ip>", not "22/tcp" (review, 27.10.2026)
        self.assertEqual(extra["proto"], "any")
        self.assertEqual(extra["comment"], "ssh-transition")
        self.assertEqual([a["ip"] for a in extra["allowed_ips"]], ["198.51.100.7", "203.0.113.5"])

    def test_patch_is_idempotent(self):
        cfg = _config()
        sh.apply_transition_to_config(cfg, (22, 16667), IPS)
        sh.apply_transition_to_config(cfg, (22, 16667), IPS)
        self.assertEqual(len(cfg["ufw"]["restricted_ports"]), 2)


class AuditSshTransitionTest(_TempCentral):
    def setUp(self):
        super().setUp()
        self.sshd_config = Path(self.tmp.name) / "sshd_config"
        self.dropins = Path(self.tmp.name) / "sshd_config.d"
        for name, value in (("SSHD_CONFIG", self.sshd_config), ("SSHD_DROPIN_DIR", self.dropins)):
            p = mock.patch.object(sh, name, value)
            p.start()
            self.addCleanup(p.stop)
        sh.Report.current = "ssh"

    def _audit(self, cfg, apply=False):
        with redirect_stdout(io.StringIO()):
            with mock.patch.object(sh, "run", return_value="") as fake:
                sh.audit_ssh(cfg, apply=apply, force=True)
        return fake

    def _findings(self, level):
        entry = sh.Report.modules.get("ssh", {"findings": []})
        return [f["text"] for f in entry["findings"] if f["level"] == level]

    def test_expected_ports_without_marker_is_config_port(self):
        self.assertEqual(sh.expected_ssh_ports(_config()), [16667])

    def test_expected_ports_with_marker_is_old_and_new(self):
        sh.write_transition(22, 16667)
        self.assertEqual(sh.expected_ssh_ports(_config()), [22, 16667])

    def test_audit_ok_when_sshd_config_has_both_ports_during_transition(self):
        sh.write_transition(22, 16667)
        self.sshd_config.write_text("Port 22\nPort 16667\nPermitRootLogin yes\n")
        self._audit(_config())
        self.assertEqual(self._findings("fail"), [])
        self.assertEqual(self._findings("warn"),
                         ["Portwechsel läuft: anmelden über 16667, dann ups"])

    def test_audit_fails_on_single_old_port_without_marker(self):
        self.sshd_config.write_text("Port 22\nPermitRootLogin yes\n")
        self._audit(_config())
        self.assertEqual(self._findings("fail"), ["Port: 22 (erwartet: 16667)"])

    def test_marker_conflicting_with_env_is_a_fail_finding(self):
        sh.write_transition(22, 2200)
        self.sshd_config.write_text("Port 22\nPort 2200\nPermitRootLogin yes\n")
        self._audit(_config(port=16667))
        fails = self._findings("fail")
        self.assertTrue(any("2200" in f and "16667" in f for f in fails), fails)

    def test_apply_during_transition_writes_two_port_lines(self):
        sh.write_transition(22, 16667)
        self.sshd_config.write_text("Port 22\nPermitRootLogin yes\n")
        fake = self._audit(_config(), apply=True)
        self.assertEqual(self.sshd_config.read_text().splitlines(),
                         ["Port 22", "Port 16667", "PermitRootLogin yes"])
        commands = [c.args[0] for c in fake.call_args_list]
        self.assertTrue(any(c.startswith("sshd -t -f") for c in commands), commands)
        self.assertIn("systemctl reload ssh", commands)

    def test_apply_without_marker_writes_single_new_port(self):
        self.sshd_config.write_text("Port 22\nPort 16667\nPermitRootLogin yes\n")
        self._audit(_config(), apply=True)
        self.assertEqual(self.sshd_config.read_text().splitlines(),
                         ["Port 16667", "PermitRootLogin yes"])


class NoRebootTest(_TempCentral):
    def test_no_reboot_flag_forces_auto_reboot_false(self):
        seen = {}

        def fake_updates(config, apply=False, force=False):
            seen["auto_reboot"] = config["auto_updates"]["auto_reboot"]

        cfg_path = Path(self.tmp.name) / "hardening_config.yaml"
        cfg_path.write_text("ssh:\n  port: 16667\nauto_updates:\n  enabled: true\n"
                            "  auto_reboot: true\n")
        funcs = {name: (fake_updates if name == "auto_updates" else
                        (lambda *a, **k: None)) for name in sh.MODULE_ORDER}
        with redirect_stdout(io.StringIO()), \
                mock.patch.object(sh.os, "geteuid", return_value=0), \
                mock.patch.object(sh, "seed_central_dir"), \
                mock.patch.object(sh, "load_env", return_value={}), \
                mock.patch.object(sh, "check_prerequisites", return_value=[]), \
                mock.patch.object(sh, "validate_config", return_value=[]), \
                mock.patch.object(sh, "module_functions", return_value=funcs):
            sh.main(["--apply", "--no-reboot", "-m", "auto_updates", "-c", str(cfg_path)])
        self.assertIs(seen.get("auto_reboot"), False)


class _TransitionCli(_TempCentral):
    """begin/finish/status with every probe replaced; run() is recorded."""

    def setUp(self):
        super().setUp()
        self.sshd_config = Path(self.tmp.name) / "sshd_config"
        self.sshd_config.write_text("Include /etc/ssh/sshd_config.d/*.conf\nPort 22\nPermitRootLogin yes\n")
        self.dropins = Path(self.tmp.name) / "sshd_config.d"
        self.dropins.mkdir()
        for name, value in (("SSHD_CONFIG", self.sshd_config), ("SSHD_DROPIN_DIR", self.dropins)):
            p = mock.patch.object(sh, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.commands = []
        self.listen = [22]
        self.peers = {22: ["198.51.100.7"], 16667: []}
        self.banner_ok = True
        self.socket_active = False
        self.other_listener = False
        self.applied = []

        def fake_run(cmd, check=False, timeout=30):
            self.commands.append(cmd)
            if cmd == "systemctl is-active ssh.service":
                return "active"
            return ""  # sshd -t: valid; everything else: silent success

        def fake_module(name):
            def module(config, apply=False, force=False):
                self.applied.append((name, apply, force, dict(config.get("ufw", {}))))
            return module

        funcs = {name: fake_module(name) for name in sh.MODULE_ORDER}
        patches = [
            mock.patch.object(sh, "run", side_effect=fake_run),
            mock.patch.object(sh, "_sshd_listen_ports", side_effect=lambda: list(self.listen)),
            mock.patch.object(sh, "_established_peers",
                              side_effect=lambda port: list(self.peers.get(port, []))),
            mock.patch.object(sh, "_ssh_banner_ok", side_effect=lambda host, port, timeout=5: self.banner_ok),
            mock.patch.object(sh, "_ssh_socket_active", side_effect=lambda: self.socket_active),
            mock.patch.object(sh, "_port_in_use_by_other", side_effect=lambda port: self.other_listener),
            mock.patch.object(sh, "module_functions", return_value=funcs),
            mock.patch.object(sh, "backup_file", side_effect=self._backup),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _backup(self, path):
        backup = Path(str(path) + ".bak")
        backup.write_text(Path(path).read_text())
        return str(backup)

    def _begin(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = sh.ssh_transition_begin(_config(), IPS)
        return code, out.getvalue()

    def _finish(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = sh.ssh_transition_finish(_config(), IPS)
        return code, out.getvalue()


class StatusTest(_TempCentral):
    def test_status_none_and_pending(self):
        self.assertEqual(sh.ssh_transition_status(), "none")
        sh.write_transition(22, 16667)
        self.assertEqual(sh.ssh_transition_status(), "pending 22 -> 16667")


class BeginTest(_TransitionCli):
    def test_begin_noop_when_only_new_port(self):
        self.listen = [16667]
        code, _ = self._begin()
        self.assertEqual(code, 0)
        self.assertEqual(self.commands, [])
        self.assertIsNone(sh.read_transition())

    def test_begin_refuses_without_allowed_ips(self):
        with redirect_stdout(io.StringIO()):
            code = sh.ssh_transition_begin(_config(), [])
        self.assertEqual(code, 1)
        self.assertIsNone(sh.read_transition())

    def test_begin_refuses_dropin_port_and_names_file(self):
        (self.dropins / "50-cloud.conf").write_text("Port 2222\n")
        code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertIn("50-cloud.conf", out)
        self.assertIsNone(sh.read_transition())

    def test_begin_refuses_port_in_use(self):
        self.other_listener = True
        code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertIn("16667", out)

    def test_begin_refuses_unlisted_peer(self):
        self.peers[22] = ["198.51.100.7", "192.0.2.99"]
        code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertIn("192.0.2.99", out)
        self.assertEqual(self.commands, [])

    def test_begin_refuses_marker_env_mismatch(self):
        sh.write_transition(22, 2200)
        code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertIn("2200", out)
        self.assertIn("16667", out)

    def test_begin_switches_off_ssh_socket_when_active(self):
        self.socket_active = True
        with mock.patch.object(sh, "_sshd_listen_ports",
                               side_effect=lambda: [22, 16667] if "systemctl reload ssh" in self.commands else [22]):
            code, _ = self._begin()
        self.assertEqual(code, 0)
        self.assertIn("systemctl disable --now ssh.socket", self.commands)
        self.assertIn("systemctl enable --now ssh.service", self.commands)
        self.assertLess(self.commands.index("systemctl disable --now ssh.socket"),
                        self.commands.index("systemctl reload ssh"))

    def test_begin_reverts_the_socket_switch_when_ssh_service_does_not_start(self):
        self.socket_active = True

        def fake_run(cmd, check=False, timeout=30):
            self.commands.append(cmd)
            if cmd == "systemctl is-active ssh.service":
                return "failed"
            return ""
        with mock.patch.object(sh, "run", side_effect=fake_run):
            code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertIn("systemctl enable --now ssh.socket", self.commands)
        self.assertNotIn("systemctl reload ssh", self.commands)
        self.assertIsNone(sh.read_transition())
        self.assertIn("ssh.service", out)

    def test_begin_writes_both_ports_marker_and_applies_ufw_fail2ban_ssh(self):
        # after the reload sshd reports both ports
        def listen_after_reload():
            return [22, 16667] if "systemctl reload ssh" in self.commands else [22]
        with mock.patch.object(sh, "_sshd_listen_ports", side_effect=listen_after_reload):
            code, _ = self._begin()
        self.assertEqual(code, 0)
        self.assertEqual(self.sshd_config.read_text().splitlines(),
                         ["Include /etc/ssh/sshd_config.d/*.conf", "Port 22", "Port 16667",
                          "PermitRootLogin yes"])
        self.assertEqual(sh.read_transition(), (22, 16667))
        self.assertTrue(any(c.startswith("sshd -t -f") for c in self.commands))
        self.assertIn("systemctl reload ssh", self.commands)
        self.assertEqual([a[0] for a in self.applied], ["ufw", "fail2ban", "ssh"])
        self.assertTrue(all(a[1] and a[2] for a in self.applied))
        # the ufw module saw the transitional rule for the old port
        rules = self.applied[0][3]["restricted_ports"]
        self.assertEqual([r["port"] for r in rules], [16667, 22])

    def test_begin_accepts_sshd_already_on_both_ports(self):
        self.listen = [22, 16667]
        self.sshd_config.write_text("Port 22\nPort 16667\nPermitRootLogin yes\n")
        code, _ = self._begin()
        self.assertEqual(code, 0)
        self.assertEqual(self.sshd_config.read_text().count("Port "), 2)
        self.assertNotIn("systemctl reload ssh", self.commands)
        self.assertEqual(sh.read_transition(), (22, 16667))
        self.assertEqual([a[0] for a in self.applied], ["ufw", "fail2ban", "ssh"])

    def test_begin_restores_backup_when_banner_fails(self):
        original = self.sshd_config.read_text()
        self.banner_ok = False
        self.listen = [22]
        with mock.patch.object(sh, "_sshd_listen_ports",
                               side_effect=lambda: [22, 16667] if "systemctl reload ssh" in self.commands else [22]):
            code, out = self._begin()
        self.assertEqual(code, 1)
        self.assertEqual(self.sshd_config.read_text(), original)
        self.assertEqual(self.commands.count("systemctl reload ssh"), 2)
        self.assertIsNone(sh.read_transition())
        self.assertEqual(self.applied, [])

    def test_begin_fails_when_sshd_t_rejects(self):
        original = self.sshd_config.read_text()

        def fake_run(cmd, check=False, timeout=30):
            self.commands.append(cmd)
            return "bad option" if cmd.startswith("sshd -t -f") else ""
        with mock.patch.object(sh, "run", side_effect=fake_run):
            code, _ = self._begin()
        self.assertEqual(code, 1)
        self.assertEqual(self.sshd_config.read_text(), original)
        self.assertNotIn("systemctl reload ssh", self.commands)
        self.assertIsNone(sh.read_transition())


class FinishTest(_TransitionCli):
    def test_finish_none_without_marker(self):
        code, out = self._finish()
        self.assertEqual((code, out.strip()), (0, "none"))

    def test_finish_pending_without_peer_on_new(self):
        sh.write_transition(22, 16667)
        self.listen = [22, 16667]
        code, out = self._finish()
        self.assertEqual((code, out.strip()), (0, "pending 22 -> 16667"))
        self.assertEqual(sh.read_transition(), (22, 16667))
        self.assertEqual(self.commands, [])

    def test_finish_ignores_unlisted_peer(self):
        sh.write_transition(22, 16667)
        self.listen = [22, 16667]
        self.peers[16667] = ["192.0.2.99", "127.0.0.1"]
        code, out = self._finish()
        self.assertEqual(out.strip(), "pending 22 -> 16667")
        self.assertEqual(sh.read_transition(), (22, 16667))

    def test_finish_closes_old_port_and_deletes_rules(self):
        sh.write_transition(22, 16667)
        self.listen = [22, 16667]
        self.sshd_config.write_text("Port 22\nPort 16667\nPermitRootLogin yes\n")
        self.peers[16667] = ["203.0.113.5"]
        code, out = self._finish()
        self.assertEqual((code, out.strip()), (0, "closed 22 -> 16667"))
        self.assertEqual(self.sshd_config.read_text().splitlines(),
                         ["Port 16667", "PermitRootLogin yes"])
        self.assertIn("systemctl reload ssh", self.commands)
        deletes = [c for c in self.commands if c.startswith("ufw delete")]
        self.assertEqual(deletes, ["ufw delete allow from 198.51.100.7 to any port 22",
                                   "ufw delete allow from 203.0.113.5 to any port 22"])
        self.assertIsNone(sh.read_transition())

    def test_finish_refuses_marker_env_mismatch(self):
        sh.write_transition(22, 2200)
        self.peers[2200] = ["203.0.113.5"]
        code, out = self._finish()
        self.assertEqual(code, 1)
        self.assertIn("2200", out)
        self.assertEqual(sh.read_transition(), (22, 2200))


class CliDispatchTest(_TempCentral):
    def test_status_needs_no_root_and_prints_none(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(sh.os, "geteuid", return_value=1000):
            with self.assertRaises(SystemExit) as ctx:
                sh.main(["--ssh-transition", "status"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), "none")

    def test_begin_with_apply_is_a_usage_error(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx, \
                mock.patch("sys.stderr", io.StringIO()):
            sh.main(["--ssh-transition", "begin", "--apply"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
