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
        self.assertEqual(extra["proto"], "tcp")
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


if __name__ == "__main__":
    unittest.main()
