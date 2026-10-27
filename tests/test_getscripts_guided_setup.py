"""
Tests for the guided first setup in getScripts.py (9.35.0, 27.10.2026).

After the fresh-server fixes of 9.34.0 the first run still ended in
confusion: the readiness report told the operator to install the maintenance
cron by hand, a host with Docker but no Odoo yet was treated as a lost
configuration, and the hardening offer refused the very port change the
operator had just asked for. This file pins the replacement: getScripts
installs the cron itself, knows the fresh state, asks one question and lets
server_hardening.py carry the port change as a transition.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:
    python3 -m unittest tests.test_getscripts_guided_setup -v
"""

import inspect
import io
import os
import subprocess
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


def _completed(code=0, out=""):
    return subprocess.CompletedProcess(["x"], code, out, "")


class MaintenanceCronTest(unittest.TestCase):
    """getScripts installs /etc/cron.d/myodoo-maintenance itself."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-cron-")
        self.script = os.path.join(self.home, "setup-maintenance-cron.sh")
        with open(self.script, "w") as handle:
            handle.write("#!/bin/bash\n")
        self.cron_file = os.path.join(self.home, "cron.d-file")
        patch_path = mock.patch.object(gs, "MAINTENANCE_CRON_PATH", self.cron_file)
        patch_path.start()
        self.addCleanup(patch_path.stop)

    def _run(self, docker=True, rc=0):
        records = []
        with mock.patch.object(gs.shutil, "which",
                               side_effect=lambda n: "/usr/bin/docker" if (docker and n == "docker") else None), \
                mock.patch.object(gs, "run_command", return_value=_completed(rc)) as run, \
                mock.patch.object(gs, "record_install", side_effect=lambda *a: records.append(a)):
            gs.ensure_maintenance_cron(self.home)
        return run, records

    def test_silent_without_docker(self):
        run, records = self._run(docker=False)
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_silent_when_cron_file_exists(self):
        with open(self.cron_file, "w") as handle:
            handle.write("# cron\n")
        run, records = self._run()
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_silent_when_script_missing(self):
        os.remove(self.script)
        run, records = self._run()
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_runs_script_and_records_installed(self):
        run, records = self._run()
        command = run.call_args.args[0]
        self.assertIn("setup-maintenance-cron.sh", command)
        self.assertTrue(command.startswith("bash "), command)
        self.assertEqual(records[0][:2], ("maintenance cron", "installed"))

    def test_records_failed_with_rerun_hint(self):
        run, records = self._run(rc=1)
        self.assertEqual(records[0][:2], ("maintenance cron", "failed"))
        self.assertIn(self.script, records[0][2])


class MainOrderTest(unittest.TestCase):
    def test_cron_runs_after_install_packages_before_migrate(self):
        source = inspect.getsource(gs.main)
        packages = source.index("run_install_packages(package_info)")
        cron = source.index("ensure_maintenance_cron(_myhome)")
        migrate = source.index("migrate_legacy_csv(_myhome)")
        self.assertLess(packages, cron)
        self.assertLess(cron, migrate)


class FreshServerTest(unittest.TestCase):
    """Docker installed, zero containers, no YAML: a fresh server, not a lost one."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-fresh-")

    def _fresh(self, docker=True, containers=False, yaml=False):
        if yaml:
            with open(os.path.join(self.home, "docker2update.yaml"), "w") as handle:
                handle.write("defaults: {}\n")
        with mock.patch.object(gs.shutil, "which",
                               side_effect=lambda n: "/usr/bin/docker" if (docker and n == "docker") else None), \
                mock.patch.object(gs, "_any_containers", return_value=containers):
            return gs.is_fresh_server(self.home)

    def test_fresh_when_docker_zero_containers_no_yaml(self):
        self.assertTrue(self._fresh())

    def test_not_fresh_when_yaml_exists(self):
        self.assertFalse(self._fresh(yaml=True))

    def test_not_fresh_when_docker_unreadable(self):
        self.assertFalse(self._fresh(containers=None))

    def test_not_fresh_with_containers(self):
        self.assertFalse(self._fresh(containers=True))

    def test_not_fresh_without_docker(self):
        self.assertFalse(self._fresh(docker=False))

    def test_noconfig_offer_silent_on_fresh_server(self):
        out = io.StringIO()
        out.isatty = lambda: True
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(gs, "_any_containers", return_value=False), \
                mock.patch.object(gs, "_prompt", side_effect=AssertionError("must not prompt")), \
                mock.patch("sys.stdin", io.StringIO()), mock.patch("sys.stdout", out), \
                mock.patch.object(gs, "_active_noconfig_jobs", return_value={"container2backup": True}):
            gs.offer_noconfig_recovery(self.home)
        self.assertEqual(out.getvalue(), "")

    def test_main_prints_next_step_after_readiness(self):
        source = inspect.getsource(gs.main)
        readiness = source.index("print_readiness_report(_myhome)")
        fresh = source.index("is_fresh_server(_myhome)")
        done = source.index('"Script completed successfully!"')
        self.assertLess(readiness, fresh)
        self.assertLess(fresh, done)
        self.assertIn("Noch keine Odoo-Instanz. Nächster Schritt: wizup", source)


ENV = {"SSH_PORT": "16667", "ALLOWED_IP_1": "198.51.100.7", "ALLOWED_IP_2": "203.0.113.5"}


def _area(check_id, modules, status="fail"):
    return {"check_id": check_id, "modules": list(modules), "on_fail": "FAIL",
            "status": status, "findings": []}


def _audit(*areas):
    return {"version": "1.12.0", "env": {}, "error": None, "areas": list(areas)}


class QuestionTextTest(unittest.TestCase):
    """One question names what will happen; nothing else is asked."""

    def test_question_lists_ips_and_port_change(self):
        text = gs._hardening_question(
            [_area("hardening_firewall", ["ufw"]), _area("hardening_fail2ban", ["fail2ban"]),
             _area("hardening_ssh", ["ssh"])], ENV, [22])
        self.assertIn("Sicherheits-Härtung: Firewall (UFW), fail2ban, SSH weichen ab.", text)
        self.assertIn("SSH-Port 16667 statt 22", text)
        self.assertIn("Zugriff nur von 198.51.100.7, 203.0.113.5", text)
        self.assertIn("Firewall an", text)
        self.assertIn("Port 22 bleibt offen, bis du dich einmal über 16667 angemeldet hast", text)
        self.assertIn("Hetzner Cloud Firewall", text)
        self.assertIn("Diese Sitzung offen lassen.", text)

    def test_question_without_port_change_has_no_port_sentence(self):
        text = gs._hardening_question([_area("hardening_firewall", ["ufw"])], ENV, [16667])
        self.assertNotIn("statt", text)
        self.assertNotIn("bleibt offen", text)
        self.assertNotIn("Hetzner", text)
        self.assertIn("Sicherheits-Härtung: Firewall (UFW) weicht ab.", text)

    def test_question_updates_clause_says_without_reboot(self):
        text = gs._hardening_question([_area("hardening_updates", ["auto_updates"])], ENV, [16667])
        self.assertIn("automatische Sicherheitsupdates (ohne nächtlichen Neustart)", text)
        self.assertNotIn("Zugriff nur von", text)


class _OfferHarness(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-offer-")
        self.script = os.path.join(self.home, "server_hardening.py")
        open(self.script, "w").close()
        self.env_path = os.path.join(self.home, gs.HARDENING_ENV_RELATIVE)
        os.makedirs(os.path.dirname(self.env_path))
        self.write_env("SSH_PORT=16667\nALLOWED_IP_1=198.51.100.7\nALLOWED_IP_2=203.0.113.5\n")
        self.commands = []
        self.answers = []
        self.printed = []
        self.statuses = []
        self.records = []
        self.begin_rc = 0

        def fake_run(command, **kwargs):
            self.commands.append(command)
            rc = self.begin_rc if "--ssh-transition begin" in command else 0
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

        patches = [
            mock.patch.object(gs.sys.stdin, "isatty", return_value=True),
            mock.patch.object(gs.sys.stdout, "isatty", return_value=True),
            mock.patch.object(gs, "run_command", side_effect=fake_run),
            mock.patch("builtins.input", side_effect=lambda _p="": self.answers.pop(0)),
            mock.patch("builtins.print", side_effect=lambda *a, **k: self.printed.append(" ".join(map(str, a)))),
            mock.patch.object(gs, "status", side_effect=lambda m="": self.statuses.append(m)),
            mock.patch.object(gs, "record_install", side_effect=lambda *a: self.records.append(a)),
            mock.patch.object(gs, "_ssh_listen_ports", return_value=[22]),
            mock.patch.object(gs, "_ssh_peers", return_value=["198.51.100.7"]),
            mock.patch.object(gs, "_any_containers", return_value=False),
            mock.patch.object(gs, "_muted_check_ids", return_value=set()),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_env(self, text):
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def offer(self, audit):
        with mock.patch.object(gs, "_hardening_audit", return_value=audit):
            gs.offer_security_hardening(self.home)

    def applied(self):
        return [c.split(" -m ", 1)[1] for c in self.commands if " --apply " in c]


class OfferTest(_OfferHarness):
    def test_only_muted_areas_asks_nothing(self):
        with mock.patch.object(gs, "_muted_check_ids", return_value={"hardening_firewall"}):
            self.offer(_audit(_area("hardening_firewall", ["ufw"])))
        self.assertEqual(self.commands, [])
        self.assertEqual(self.answers, [])

    def test_j_with_port_change_runs_begin_first(self):
        self.answers = ["j"]
        self.offer(_audit(_area("hardening_firewall", ["ufw"]), _area("hardening_ssh", ["ssh"]),
                          _area("hardening_fail2ban", ["fail2ban"]),
                          _area("hardening_kernel", ["sysctl"], "warn")))
        self.assertIn("--ssh-transition begin", self.commands[0])
        self.assertEqual(self.applied(), ["sysctl"])  # ufw/fail2ban/ssh done by begin
        self.assertEqual(self.records[-1][:2], ("hardening", "installed"))

    def test_j_without_port_change_runs_apply_guarded(self):
        self.answers = ["j"]
        with mock.patch.object(gs, "_ssh_listen_ports", return_value=[16667]):
            self.offer(_audit(_area("hardening_kernel", ["sysctl"], "warn"),
                              _area("hardening_firewall", ["ufw"]),
                              _area("hardening_integrity", ["auditd", "aide"])))
        self.assertFalse(any("--ssh-transition" in c for c in self.commands))
        self.assertEqual(self.applied(), ["sysctl auditd", "ufw", "aide"])

    def test_other_answer_prints_later_line_with_four_hints(self):
        self.answers = [""]
        with mock.patch.object(gs, "_ssh_listen_ports", return_value=[16667]):
            self.offer(_audit(_area("hardening_firewall", ["ufw"])))
        self.assertEqual(self.commands, [])
        later = [m for m in self.statuses if m.startswith("Später")]
        self.assertEqual(len(later), 1)
        for hint in ("chk", "server_hardening.py --help", "ownerp_mute.py", "-m auto_updates"):
            self.assertIn(hint, later[0])

    def test_begin_failure_records_failed_and_stops(self):
        self.begin_rc = 1
        self.answers = ["j"]
        self.offer(_audit(_area("hardening_ssh", ["ssh"]), _area("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), [])
        self.assertEqual(self.records[-1][:2], ("hardening", "failed"))
        self.assertIn("ups fragt beim nächsten Mal erneut", self.records[-1][2])

    def test_auto_updates_gets_no_reboot_and_no_question(self):
        self.answers = ["j"]
        with mock.patch.object(gs, "_ssh_listen_ports", return_value=[16667]):
            self.offer(_audit(_area("hardening_updates", ["auto_updates"])))
        self.assertEqual(self.applied(), ["auto_updates"])
        self.assertIn("--no-reboot", self.commands[0])
        self.assertEqual(self.answers, [])

    def test_foreign_peer_means_no_question(self):
        with mock.patch.object(gs, "_ssh_peers", return_value=["198.51.100.7", "192.0.2.99"]), \
                mock.patch.object(gs, "_ssh_listen_ports", return_value=[16667]):
            self.offer(_audit(_area("hardening_firewall", ["ufw"])))
        self.assertEqual(self.commands, [])
        self.assertTrue(any("192.0.2.99" in m for m in self.statuses), self.statuses)

    def test_muted_ssh_area_never_starts_the_transition(self):
        # SSH muted on purpose, firewall pending, SSH_PORT differs from the
        # live port: the mute keeps the port where it is - and the firewall
        # must then wait too, or UFW would open only the port sshd is not on.
        self.answers = ["j"]
        with mock.patch.object(gs, "_muted_check_ids", return_value={"hardening_ssh"}):
            self.offer(_audit(_area("hardening_firewall", ["ufw"]), _area("hardening_ssh", ["ssh"]),
                              _area("hardening_kernel", ["sysctl"], "warn")))
        self.assertFalse(any("--ssh-transition" in c for c in self.commands), self.commands)
        self.assertEqual(self.applied(), ["sysctl"])
        self.assertTrue(any("stummgeschaltet" in m for m in self.statuses), self.statuses)

    def test_foreign_peer_does_not_block_harmless_areas(self):
        self.answers = ["j"]
        with mock.patch.object(gs, "_ssh_peers", return_value=["192.0.2.99"]), \
                mock.patch.object(gs, "_ssh_listen_ports", return_value=[16667]):
            self.offer(_audit(_area("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["sysctl"])


class BlockersTest(unittest.TestCase):
    def test_blockers_no_longer_mention_port_change_or_socket(self):
        self.assertEqual(gs._lockout_blockers(ENV, [22], ["198.51.100.7"]), [])
        self.assertEqual(gs._lockout_blockers(ENV, [22, 16667], ["198.51.100.7"]), [])
        self.assertFalse(hasattr(gs, "_ssh_socket_active"))

    def test_unlisted_peer_still_blocks(self):
        blockers = gs._lockout_blockers(ENV, [22], ["198.51.100.7", "192.0.2.99"])
        self.assertTrue(any("192.0.2.99" in b for b in blockers), blockers)

    def test_no_ips_and_unreadable_state_block(self):
        self.assertTrue(gs._lockout_blockers({"SSH_PORT": "22"}, [22], ["198.51.100.7"]))
        self.assertTrue(gs._lockout_blockers(ENV, [], ["198.51.100.7"]))
        self.assertTrue(gs._lockout_blockers(ENV, [22], None))

    def test_port_change_steps_gone(self):
        self.assertFalse(hasattr(gs, "PORT_CHANGE_STEPS"))


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gs-finish-")
        open(os.path.join(self.home, "server_hardening.py"), "w").close()
        self.marker = os.path.join(self.home, gs.SSH_TRANSITION_RELATIVE)
        os.makedirs(os.path.dirname(self.marker))

    def _run(self, stdout, rc=0, marker=True):
        if marker:
            with open(self.marker, "w") as handle:
                handle.write("22 16667\n")
        records = []
        with mock.patch.object(gs, "run_command",
                               return_value=_completed(rc, stdout)) as run, \
                mock.patch.object(gs, "record_install", side_effect=lambda *a: records.append(a)):
            gs.finish_ssh_transition(self.home)
        return run, records

    def test_finish_silent_without_marker(self):
        run, records = self._run("none", marker=False)
        run.assert_not_called()
        self.assertEqual(records, [])

    def test_finish_records_updated_on_closed(self):
        run, records = self._run("closed 22 -> 16667\n")
        self.assertIn("--ssh-transition finish", run.call_args.args[0])
        self.assertEqual(records[0][:2], ("ssh port", "updated"))
        self.assertIn("22 geschlossen", records[0][2])
        self.assertIn("16667", records[0][2])

    def test_finish_records_ok_on_pending(self):
        _run, records = self._run("pending 22 -> 16667\n")
        self.assertEqual(records[0][:2], ("ssh port", "ok"))
        self.assertIn("anmelden über 16667", records[0][2])

    def test_finish_reads_bytes_stdout(self):
        # run_command() captures without text=True: stdout is bytes. The
        # first version matched a str regex against it and took every ups
        # down while a transition was pending (review, 27.10.2026).
        with open(self.marker, "w") as handle:
            handle.write("22 16667\n")
        records = []
        completed = subprocess.CompletedProcess(["x"], 0, b"pending 22 -> 16667\n", b"")
        with mock.patch.object(gs, "run_command", return_value=completed), \
                mock.patch.object(gs, "record_install", side_effect=lambda *a: records.append(a)):
            gs.finish_ssh_transition(self.home)
        self.assertEqual(records[0][:2], ("ssh port", "ok"))

    def test_finish_records_failed_on_conflict(self):
        _run, records = self._run("conflict 22 -> 16667: x\n", rc=1)
        self.assertEqual(records[0][:2], ("ssh port", "failed"))

    def test_main_calls_finish_after_install_packages(self):
        source = inspect.getsource(gs.main)
        self.assertLess(source.index("run_install_packages(package_info)"),
                        source.index("finish_ssh_transition(_myhome)"))
        self.assertLess(source.index("finish_ssh_transition(_myhome)"),
                        source.index("offer_security_hardening(_myhome)"))


class SshBlockTextTest(unittest.TestCase):
    def test_ssh_block_text_names_the_question_at_the_end(self):
        source = inspect.getsource(gs.configure_ssh_access)
        self.assertNotIn("nur festgelegt, nicht geändert", source)
        self.assertNotIn("sechs Schritte", source)
        self.assertIn("Die Härtung am Ende der Installation stellt den Port um und fragt vorher einmal.",
                      source)


if __name__ == "__main__":
    unittest.main()
