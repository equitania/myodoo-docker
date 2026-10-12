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


ALLOWED = [{"n": 1, "ip": "192.0.2.1", "comment": "Office A"},
           {"n": 2, "ip": "192.0.2.10", "comment": ""}]


class MaskTest(unittest.TestCase):
    def test_ip_becomes_comment_or_slot(self):
        text = "Port 22 von 192.0.2.1 FEHLT; Port 22 von 192.0.2.10 FEHLT"
        self.assertEqual(sh.mask_ips(text, ALLOWED),
                         "Port 22 von Office A FEHLT; Port 22 von ALLOWED_IP_2 FEHLT")

    def test_mask_does_not_cut_a_longer_ip(self):
        masked = sh.mask_ips("from 192.0.2.10", [ALLOWED[0]])
        self.assertEqual(masked, "from 192.0.2.10")

    def test_allowlist_entries_carry_their_slot(self):
        with mock.patch.dict(os.environ, {"ALLOWED_IP_3": "192.0.2.30"}, clear=True):
            allowed = sh.inject_allowed_ips({"ufw": {"restricted_ports": []}})
        self.assertEqual(allowed, [{"n": 3, "ip": "192.0.2.30", "comment": ""}])


def _fake_module(fail_text=None, warn_text=None, noise=False):
    def audit(config, apply=False, force=False):
        if noise:
            print("stray output that must not reach the JSON")
        sh.ok("fine")
        if warn_text:
            sh.warn(warn_text)
        if fail_text:
            sh.fail(fail_text)
    return audit


class JsonAuditTest(unittest.TestCase):
    def fakes(self, **overrides):
        functions = {name: _fake_module() for name in sh.MODULE_ORDER}
        functions.update(overrides)
        return mock.patch.object(sh, "module_functions", return_value=functions)

    def test_areas_follow_the_worst_module(self):
        env = {"path": "/x/.env", "present": True, "loaded": True,
               "ssh_port": 22, "allowed_ips": 1}
        with self.fakes(ufw=_fake_module(fail_text="UFW ist NICHT aktiv"),
                        sysctl=_fake_module(warn_text="x")):
            result = sh.run_json_audit({}, ALLOWED, env)
        areas = {a["check_id"]: a for a in result["areas"]}
        self.assertEqual([a[0] for a in sh.AREAS], [a["check_id"] for a in result["areas"]])
        self.assertEqual(areas["hardening_firewall"]["status"], "fail")
        self.assertEqual(areas["hardening_kernel"]["status"], "warn")
        self.assertEqual(areas["hardening_ssh"]["status"], "ok")
        self.assertEqual(areas["hardening_firewall"]["findings"],
                         [{"module": "ufw", "level": "fail", "text": "UFW ist NICHT aktiv"}])
        self.assertIsNone(result["error"])

    def test_no_ip_in_the_document(self):
        with self.fakes(ufw=_fake_module(fail_text="Port 22 von 192.0.2.1 FEHLT")):
            result = sh.run_json_audit({}, ALLOWED, {})
        self.assertNotIn("192.0.2.1", json.dumps(result))

    def test_stray_prints_do_not_leak(self):
        out = io.StringIO()
        with self.fakes(ufw=_fake_module(noise=True)), redirect_stdout(out):
            sh.run_json_audit({}, [], {})
        self.assertEqual(out.getvalue(), "")

    # Hermetic: __file__ points into a temp dir, so a developer's own
    # scripts/.env is never loaded; the real YAML is passed with -c.
    REPO_YAML = str(Path(_PATH).resolve().parent / "hardening_config.yaml")

    def hermetic(self, tmp):
        return mock.patch.object(sh, "__file__", str(Path(tmp) / "server_hardening.py"))

    def test_json_mode_writes_nothing_and_prints_one_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            central = Path(tmp) / "cfg"
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLOWED_IP_")}
            env.update(SSH_PORT="22", ALLOWED_IP_1="192.0.2.1")
            with self.fakes(), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", central), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out):
                sh.main(["--json", "-c", self.REPO_YAML])
            self.assertFalse(central.exists())
            self.assertEqual(sorted(os.listdir(tmp)), [])
        document = json.loads(out.getvalue())
        self.assertEqual(document["env"]["allowed_ips"], 1)
        self.assertEqual(document["env"]["ssh_port"], 22)
        self.assertFalse(document["env"]["present"])

    def test_json_reports_a_missing_ssh_port_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items()
                   if k != "SSH_PORT" and not k.startswith("ALLOWED_IP_")}
            with self.fakes(), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", Path(tmp) / "cfg"), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out), \
                 self.assertRaises(SystemExit) as exit_:
                sh.main(["--json", "-c", self.REPO_YAML])
        self.assertEqual(exit_.exception.code, 1)
        document = json.loads(out.getvalue())
        self.assertTrue(document["error"])
        self.assertEqual(document["areas"], [])

    def test_json_without_root_is_a_json_error(self):
        out = io.StringIO()
        with mock.patch.object(sh.os, "geteuid", return_value=1000), \
             redirect_stdout(out), self.assertRaises(SystemExit):
            sh.main(["--json"])
        self.assertIn("root", json.loads(out.getvalue())["error"])

    def test_json_and_apply_exclude_each_other(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()), \
             self.assertRaises(SystemExit):
            sh.main(["--json", "--apply"])

    def test_json_with_a_non_mapping_config_is_an_error_document(self):
        """A YAML list (or any non-mapping document) must not end as a
        traceback with empty stdout in --json mode — same contract as a
        missing/invalid config file."""
        with tempfile.TemporaryDirectory() as tmp:
            list_yaml = Path(tmp) / "list.yaml"
            list_yaml.write_text("- a\n- b\n")
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLOWED_IP_")}
            env.update(SSH_PORT="22", ALLOWED_IP_1="192.0.2.1")
            with self.fakes(), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", Path(tmp) / "cfg"), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out), \
                 self.assertRaises(SystemExit) as exit_:
                sh.main(["--json", "-c", str(list_yaml)])
        self.assertEqual(exit_.exception.code, 1)
        document = json.loads(out.getvalue())
        self.assertTrue(document["error"])
        self.assertEqual(document["areas"], [])

    def test_json_when_a_module_raises_is_an_error_document(self):
        """A crashing module must become a JSON error document, not a
        traceback with empty stdout."""
        def _raiser(config, apply=False, force=False):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLOWED_IP_")}
            env.update(SSH_PORT="22", ALLOWED_IP_1="192.0.2.1")
            with self.fakes(ufw=_raiser), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", Path(tmp) / "cfg"), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out), \
                 self.assertRaises(SystemExit) as exit_:
                sh.main(["--json", "-c", self.REPO_YAML])
        self.assertEqual(exit_.exception.code, 1)
        document = json.loads(out.getvalue())
        self.assertIn("boom", document["error"])
        self.assertEqual(document["areas"], [])


class AideBackgroundTest(unittest.TestCase):
    """The first AIDE build hashed the filesystem in the foreground and held
    `ups` for many minutes (12.10.2026). It now runs in the same transient
    unit as syspatch's rebuild."""

    def fake_run(self, active="inactive", started=True):
        calls = []

        def run(cmd, check=False, timeout=30):
            calls.append((cmd, timeout))
            if cmd.startswith("systemctl is-active"):
                return active
            if cmd.startswith("systemd-run"):
                return "started" if started else ""
            return ""
        return run, calls

    def test_unit_name_matches_syspatch(self):
        fish = (Path(_PATH).parent.parent / "fish/functions/linux/syspatch.fish").read_text(encoding="utf-8")
        self.assertIn(f"--unit={sh.AIDE_UNIT}", fish)

    def test_starts_a_low_priority_transient_unit(self):
        run, calls = self.fake_run()
        with mock.patch.object(sh, "run", run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/bin/systemd-run"):
            self.assertTrue(sh.start_aide_background(Path("/var/lib/aide/aide.db")))
        command = calls[-1][0]
        self.assertIn(f"systemd-run --unit={sh.AIDE_UNIT}", command)
        self.assertIn("IOSchedulingClass=idle", command)
        self.assertIn("aideinit -y -f", command)
        self.assertIn("mv /var/lib/aide/aide.db.new /var/lib/aide/aide.db", command)

    def test_a_running_build_is_not_started_twice(self):
        run, calls = self.fake_run(active="active")
        with mock.patch.object(sh, "run", run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/bin/systemd-run"):
            self.assertTrue(sh.start_aide_background(Path("/var/lib/aide/aide.db")))
        self.assertFalse(any(c.startswith("systemd-run") for c, _ in calls))

    def test_without_systemd_run_the_caller_falls_back(self):
        with mock.patch.object(sh.shutil, "which", return_value=None):
            self.assertIsNone(sh.start_aide_background(Path("/var/lib/aide/aide.db")))

    def test_apply_no_longer_waits_for_aideinit(self):
        run, calls = self.fake_run()
        with mock.patch.object(sh, "run", run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/bin/x"), \
             mock.patch.object(sh.Path, "exists", return_value=False), \
             mock.patch.object(sh.Path, "is_dir", return_value=False):
            sh.audit_aide({}, apply=True)
        self.assertFalse([c for c, t in calls if c.startswith("aideinit")])
        self.assertTrue([c for c, _ in calls if c.startswith("systemd-run")])

    def test_audit_counts_a_running_build_as_ok(self):
        run, _ = self.fake_run(active="active")
        before = (sh.Stats.ok_count, sh.Stats.warn_count)
        with mock.patch.object(sh, "run", run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/bin/x"), \
             mock.patch.object(sh.Path, "exists", return_value=False):
            sh.audit_aide({}, apply=False)
        self.assertEqual(sh.Stats.warn_count, before[1])
        self.assertEqual(sh.Stats.ok_count, before[0] + 2)


class Fail2banJournalBackendTest(unittest.TestCase):
    """backend = systemd without python3-systemd left fail2ban with no jail at
    all on Ubuntu 22.04 (12.10.2026) - fail2ban was already installed, so the
    package that comes with a fresh install was never added."""

    CONFIG = {"fail2ban": {"enabled": True, "banaction": "ufw", "jails": {
        "sshd": {"enabled": True, "port": "22", "backend": "systemd",
                 "journalmatch": "_SYSTEMD_UNIT=ssh.service + _COMM=sshd"},
        "nginx-http-auth": {"enabled": True, "logpath": "/var/log/nginx/error.log"},
    }}}

    def apply(self, journal=(False, True), jails_after=("2",), auth_log=True):
        journal = list(journal)
        jails_after = list(jails_after)
        calls, written, restarted = [], {}, []

        def run(cmd, check=False, timeout=30):
            calls.append(cmd)
            if "import systemd.journal" in cmd:
                return "yes" if (journal.pop(0) if journal else False) else ""
            if cmd == "systemctl restart fail2ban":
                restarted.append(True)
            if cmd.startswith("fail2ban-client status"):
                count = (jails_after.pop(0) if jails_after else "0") if restarted else "0"
                return f"Status\n|- Number of jail:\t{count}\n`- Jail list:\tsshd"
            return ""

        def exists(path):
            return {"/var/log/auth.log": auth_log}.get(path, True)

        def write_text(path_self, text, *a, **k):
            written[str(path_self)] = text

        with mock.patch.object(sh, "run", run), \
             mock.patch.object(sh, "apt_install") as apt, \
             mock.patch.object(sh, "backup_file", return_value="/etc/fail2ban/jail.backup_x.local"), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/bin/fail2ban-client"), \
             mock.patch.object(sh.shutil, "move") as move, \
             mock.patch.object(sh.shutil, "copy2") as copy2, \
             mock.patch.object(sh.os.path, "exists", side_effect=exists), \
             mock.patch.object(sh.time, "sleep"), \
             mock.patch.object(sh.Path, "write_text", write_text):
            sh.audit_fail2ban(self.CONFIG, apply=True)
        return calls, written.get("/etc/fail2ban/jail.local", ""), apt, move, copy2

    def test_missing_module_is_installed_and_the_backend_kept(self):
        calls, jail_local, apt, _, _ = self.apply(journal=(False, False, True))
        apt.assert_called_once_with("python3-systemd")
        self.assertIn("backend  = systemd", jail_local)

    def test_not_installable_falls_back_to_the_auth_log(self):
        _, jail_local, _, _, _ = self.apply(journal=(False, False, False))
        sshd = jail_local.split("[sshd]")[1].split("[")[0]
        self.assertIn("enabled  = true", sshd)
        self.assertNotIn("backend", sshd)
        self.assertNotIn("journalmatch", sshd)

    def test_no_journal_and_no_auth_log_disables_only_that_jail(self):
        _, jail_local, _, _, _ = self.apply(journal=(False, False, False), auth_log=False)
        sshd = jail_local.split("[sshd]")[1].split("[")[0]
        self.assertIn("enabled  = false", sshd)
        nginx = jail_local.split("[nginx-http-auth]")[1]
        self.assertIn("enabled  = true", nginx)

    def test_zero_jails_after_restart_restores_the_previous_file(self):
        calls, _, _, move, copy2 = self.apply(journal=(True, True), jails_after=())
        move.assert_called_once()
        self.assertTrue(move.call_args.args[1].startswith("/etc/fail2ban/jail.local.failed_"))
        copy2.assert_called_once_with("/etc/fail2ban/jail.backup_x.local", "/etc/fail2ban/jail.local")
        self.assertEqual(sum(c == "systemctl restart fail2ban" for c in calls), 2)

    def test_jails_loaded_keeps_the_new_file(self):
        _, _, _, move, copy2 = self.apply(journal=(True, True), jails_after=("2",))
        move.assert_not_called()
        copy2.assert_not_called()


if __name__ == "__main__":
    unittest.main()
