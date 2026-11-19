"""
Tests for keeping nginx.org-nginx installable and current (getScripts 9.40.0,
server-readiness 1.19.0, server_hardening 1.13.0).

Written for two hosts found on 19.11.2026: a Debian 13 server still on
1.30.6-1~trixie (unattended-upgrades never allows nginx.org), and an Ubuntu
host upgraded 22.04 -> 24.04 that ran 1.30.2-1~jammy because do-release-upgrade
left only nginx.list.distUpgrade and nginx.list~ behind. No test needs root,
apt or a network; the host names and addresses are placeholders.

Run from the repository root:

    python3 -m unittest tests.test_nginx_current -v
"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")
REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO, "scripts", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sr = _load("server_readiness", "server-readiness.py")
try:
    import yaml  # noqa: F401
    sh = _load("server_hardening", "server_hardening.py")
except ImportError:  # pragma: no cover
    sh = None

LIST_MODERN = ("deb [arch=amd64 signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] "
               "http://nginx.org/packages/ubuntu jammy nginx\n")
LIST_PLAIN = "deb http://nginx.org/packages/ubuntu jammy nginx\n"
GOOD = ("deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] "
        "https://nginx.org/packages/ubuntu noble nginx\n")
DEB822 = """\
Types: deb
URIs: https://nginx.org/packages/debian
Suites: trixie
Components: nginx
Signed-By: /usr/share/keyrings/nginx-archive-keyring.gpg
"""


def make_apt(files):
    tmp = tempfile.TemporaryDirectory()
    parts = os.path.join(tmp.name, "sources.list.d")
    os.makedirs(parts)
    for name, content in files.items():
        with open(os.path.join(parts, name), "w") as handle:
            handle.write(content)
    return tmp


class ParseTest(unittest.TestCase):
    def test_os_release(self):
        values = gs.parse_os_release('ID=ubuntu\nVERSION_CODENAME="noble"\n# x\nFOO=\n')
        self.assertEqual((values["ID"], values["VERSION_CODENAME"]), ("ubuntu", "noble"))

    def test_list_line_with_and_without_options(self):
        for text in (LIST_MODERN, LIST_PLAIN):
            found = gs.nginx_sources_in_list(text)
            self.assertEqual([s.suite for s in found], ["jammy"])

    def test_comments_and_deb_src_and_foreign_origins_do_not_count(self):
        text = ("# deb http://nginx.org/packages/ubuntu jammy nginx\n"
                "deb-src http://nginx.org/packages/ubuntu jammy nginx\n"
                "deb http://archive.example.com/ubuntu noble main\n")
        self.assertEqual(gs.nginx_sources_in_list(text), [])

    def test_deb822_active_disabled_and_src_only(self):
        self.assertEqual([s.suite for s in gs.nginx_sources_in_deb822(DEB822)], ["trixie"])
        self.assertEqual(gs.nginx_sources_in_deb822(DEB822 + "Enabled: no\n"), [])
        self.assertEqual(gs.nginx_sources_in_deb822(DEB822.replace("Types: deb", "Types: deb-src")), [])

    def test_ubuntu_leftover_with_only_ignored_files_has_no_active_source(self):
        tmp = make_apt({"nginx.list.distUpgrade": LIST_MODERN, "nginx.list~": LIST_PLAIN,
                        "nginx.list.save": LIST_PLAIN})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(gs.collect_nginx_sources(tmp.name), [])

    def test_collect_reads_list_sources_and_main_file(self):
        tmp = make_apt({"nginx.list": GOOD, "x.sources": DEB822})
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "sources.list"), "w") as handle:
            handle.write(LIST_PLAIN)
        suites = sorted(s.suite for s in gs.collect_nginx_sources(tmp.name))
        self.assertEqual(suites, ["jammy", "noble", "trixie"])


class EditTest(unittest.TestCase):
    def test_comment_out_keeps_other_lines(self):
        text = "deb http://archive.example.com/ubuntu noble main\n" + LIST_PLAIN
        new, changed = gs.comment_out_nginx_lines(text)
        self.assertTrue(changed)
        self.assertEqual(gs.nginx_sources_in_list(new), [])
        self.assertIn("deb http://archive.example.com/ubuntu noble main\n", new)

    def test_disable_deb822_sets_enabled_no(self):
        new, changed = gs.disable_nginx_deb822(DEB822)
        self.assertTrue(changed)
        self.assertEqual(gs.nginx_sources_in_deb822(new), [])
        self.assertEqual(gs.disable_nginx_deb822(new)[1], False)

    def test_repo_line(self):
        self.assertEqual(
            gs.nginx_repo_line("ubuntu", "noble"),
            "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] "
            "https://nginx.org/packages/ubuntu noble nginx\n")


def src(suite):
    return gs.NginxSource("/x", "list", suite, "https://nginx.org/packages/debian")


class DecisionTest(unittest.TestCase):
    def test_distro_version_is_never_switched(self):
        self.assertEqual(gs.decide_nginx_repo_action("1.26.3-3+deb13u1", [], "trixie"), "distro")
        self.assertEqual(gs.decide_nginx_repo_action("1.24.0-2ubuntu7", [src("noble")], "noble"), "distro")

    def test_current_when_an_entry_names_the_codename(self):
        self.assertEqual(gs.decide_nginx_repo_action("1.30.6-1~trixie", [src("trixie")], "trixie"), "current")

    def test_repair_when_none_or_wrong_codename(self):
        self.assertEqual(gs.decide_nginx_repo_action("1.30.2-1~jammy", [], "noble"), "repair")
        self.assertEqual(gs.decide_nginx_repo_action("1.30.2-1~jammy", [src("jammy")], "noble"), "repair")

    def test_candidate_parse(self):
        self.assertEqual(gs.parse_policy_candidate("nginx:\n  Installed: 1\n  Candidate: 1.30.7-1~noble\n"), "1.30.7-1~noble")
        self.assertIsNone(gs.parse_policy_candidate("  Candidate: (none)\n"))
        self.assertIsNone(gs.parse_policy_candidate(""))

    def test_upgrade_needed_equal_newer_older(self):
        def newer(a, b):
            return tuple(map(int, a.split("-")[0].split("."))) > tuple(map(int, b.split("-")[0].split(".")))
        self.assertFalse(gs.nginx_needs_upgrade("1.30.7-1~noble", "1.30.7-1~noble", newer))
        self.assertTrue(gs.nginx_needs_upgrade("1.30.6-1~noble", "1.30.7-1~noble", newer))
        self.assertFalse(gs.nginx_needs_upgrade("1.30.7-1~noble", "1.30.6-1~noble", newer))
        self.assertFalse(gs.nginx_needs_upgrade("1.30.7-1~noble", None, newer))

    def test_http2_only_when_active(self):
        self.assertTrue(gs.nginx_conf_uses_http2(["server {\n  http2 on;\n}"]))
        self.assertTrue(gs.nginx_conf_uses_http2(["listen 443 ssl http2;"]))
        self.assertFalse(gs.nginx_conf_uses_http2(["# http2 on;\n  # listen 443 ssl http2;"]))
        self.assertFalse(gs.nginx_conf_uses_http2(["listen 443 ssl;"]))
        self.assertIn("http2 off", gs.distro_nginx_advice(True))
        self.assertNotIn("http2 off", gs.distro_nginx_advice(False))

    def test_upgrade_command_keeps_conffiles_and_moves_modules_together(self):
        command = gs.nginx_upgrade_command(["nginx", "nginx-module-njs"])
        self.assertIn("--only-upgrade", command)
        self.assertIn("Dpkg::Options::=--force-confold", command)
        self.assertIn("Dpkg::Options::=--force-confdef", command)
        self.assertEqual(command[-2:], ["nginx", "nginx-module-njs"])
        rollback = gs.nginx_upgrade_command(["nginx=1.30.6-1~noble"], downgrade=True)
        self.assertIn("--allow-downgrades", rollback)
        self.assertNotIn("--only-upgrade", rollback)


class UpgradeFlowTest(unittest.TestCase):
    """_nginx_upgrade with the subprocess layer replaced."""

    def setUp(self):
        gs._install_report.clear()
        self.addCleanup(gs._install_report.clear)

    def run_flow(self, results):
        calls = []

        def fake(argv, timeout=120, input_bytes=None):
            calls.append(argv)
            return results(argv)

        patches = [mock.patch.object(gs, "_nginx_run", fake),
                   mock.patch.object(gs, "_nginx_installed_modules",
                                     return_value={"nginx-module-njs": "1.30.6-1~noble"}),
                   mock.patch.object(gs.shutil, "which", return_value="/bin/x")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        gs._nginx_upgrade("1.30.6-1~noble", "1.30.7-1~noble")
        return calls

    def test_success_is_recorded(self):
        self.run_flow(lambda argv: (0, "active"))
        self.assertEqual(gs._install_report, [("nginx", "updated", "1.30.6-1~noble -> 1.30.7-1~noble")])

    def test_config_test_failure_rolls_back_to_exact_versions(self):
        state = {"upgraded": False}

        def results(argv):
            if argv[0] == "apt-get" and "--only-upgrade" in argv:
                state["upgraded"] = True
            if argv[:2] == ["nginx", "-t"] and state["upgraded"] and not state.get("rolled"):
                return 1, "nginx: configuration file test failed"
            if "--allow-downgrades" in argv:
                state["rolled"] = True
            return 0, ""
        calls = self.run_flow(results)
        rollback = next(c for c in calls if "--allow-downgrades" in c)
        self.assertIn("nginx=1.30.6-1~noble", rollback)
        self.assertIn("nginx-module-njs=1.30.6-1~noble", rollback)
        name, status, detail = gs._install_report[0]
        self.assertEqual(status, "failed")
        self.assertIn("nginx -t failed", detail)
        self.assertIn("rolled back", detail)

    def test_failed_rollback_is_named(self):
        def results(argv):
            return (100, "E: no such version") if argv[0] == "apt-get" else (0, "")
        self.run_flow(results)
        self.assertEqual(gs._install_report[0][1], "failed")
        self.assertIn("rollback", gs._install_report[0][2])

    def test_modules_are_upgraded_in_the_same_call(self):
        calls = self.run_flow(lambda argv: (0, ""))
        upgrade = next(c for c in calls if "--only-upgrade" in c)
        self.assertIn("nginx-module-njs", upgrade)


class EnsureTest(unittest.TestCase):
    def setUp(self):
        gs._install_report.clear()
        self.addCleanup(gs._install_report.clear)

    def test_apt_runs_in_the_c_locale(self):
        # a German server answers "Installationskandidat:" otherwise
        with mock.patch.object(gs.subprocess, "run") as run, \
                mock.patch.dict(gs.os.environ, {"LANG": "de_DE.UTF-8"}):
            run.return_value = mock.Mock(returncode=0, stdout=b"", stderr=b"")
            gs._nginx_run(["apt-cache", "policy", "nginx"])
        env = run.call_args.kwargs["env"]
        self.assertEqual((env["LC_ALL"], env["LANG"]), ("C", "C"))

    def test_installed_version_needs_state_ii(self):
        self.assertEqual(gs.nginx_installed_version("ii  1.30.6-1~trixie"), "1.30.6-1~trixie")
        self.assertIsNone(gs.nginx_installed_version("rc  1.30.6-1~trixie"))
        self.assertIsNone(gs.nginx_installed_version(""))

    def test_removed_nginx_is_left_alone(self):
        # config files left behind ("rc"): no upgrade, and above all no rollback
        # that would install nginx on a host without it
        text = 'ID=debian\nVERSION_CODENAME=trixie\n'
        with mock.patch.object(gs.shutil, "which", return_value="/bin/x"), \
                mock.patch("builtins.open", mock.mock_open(read_data=text)), \
                mock.patch.object(gs, "_nginx_run", return_value=(0, "rc  1.30.6-1~trixie")) as run, \
                mock.patch.object(gs, "collect_nginx_sources") as collect:
            gs.ensure_nginx_current()
        self.assertEqual(run.call_count, 1)
        collect.assert_not_called()
        self.assertEqual(gs._install_report, [])

    def test_other_distribution_is_skipped_silently(self):
        text = 'ID=fedora\nVERSION_CODENAME=""\n'
        with mock.patch.object(gs.shutil, "which", return_value="/bin/x"), \
                mock.patch("builtins.open", mock.mock_open(read_data=text)), \
                mock.patch.object(gs, "_nginx_run") as run:
            gs.ensure_nginx_current()
        run.assert_not_called()
        self.assertEqual(gs._install_report, [])

    def test_distro_nginx_is_reported_and_not_switched(self):
        text = 'ID=debian\nVERSION_CODENAME=trixie\n'
        with mock.patch.object(gs.shutil, "which", return_value="/bin/x"), \
                mock.patch("builtins.open", mock.mock_open(read_data=text)), \
                mock.patch.object(gs, "_nginx_run", return_value=(0, "ii  1.26.3-3+deb13u1")), \
                mock.patch.object(gs.os, "geteuid", return_value=0), \
                mock.patch.object(gs, "collect_nginx_sources", return_value=[]), \
                mock.patch.object(gs, "_nginx_repair_source") as repair:
            gs.ensure_nginx_current()
        repair.assert_not_called()
        name, status, detail = gs._install_report[0]
        self.assertEqual((name, status), ("nginx", "skipped"))
        self.assertIn("not patched", detail)

    def test_an_exception_is_reported_not_raised(self):
        with mock.patch.object(gs, "_ensure_nginx_current", side_effect=RuntimeError("boom")):
            gs.ensure_nginx_current()
        self.assertEqual(gs._install_report[0][1], "failed")

    def test_step_runs_in_main_after_the_packages(self):
        with open(os.path.join(REPO, "getScripts.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertLess(source.index("run_install_packages(package_info)\n"),
                        source.index("        ensure_nginx_current()\n"))


class ReadinessCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_apt({})
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "etc"))
        self.write("etc/os-release", 'ID=ubuntu\nVERSION_CODENAME=noble\n')
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name, repo=self.tmp.name)
        # make_apt put sources.list.d in the root; the check wants root/etc/apt
        os.makedirs(os.path.join(self.tmp.name, "etc", "apt"))
        os.rename(os.path.join(self.tmp.name, "sources.list.d"),
                  os.path.join(self.tmp.name, "etc", "apt", "sources.list.d"))

    def write(self, rel, content):
        path = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(content)

    def check(self, installed="1.30.7-1~noble", policy="  Candidate: 1.30.7-1~noble\n",
              newer=1, installed_rc=0, state="ii"):
        def fake(command, timeout=15, c_locale=False):
            if command[0] == "apt-cache":
                assert c_locale, "apt-cache output is parsed: needs the C locale"
            if command[0] == "dpkg-query":
                return installed_rc, (f"{state} {installed}" if installed else "")
            if command[0] == "apt-cache":
                return 0, policy
            if command[0] == "dpkg":
                return newer, ""
            raise AssertionError(command)
        with mock.patch.object(sr, "_run", fake), \
                mock.patch.object(sr.shutil, "which", return_value="/bin/x"):
            return sr.check_nginx_repo(self.ctx)

    def test_registered(self):
        self.assertIn(sr.check_nginx_repo, sr.CHECKS)

    def test_skip_without_nginx(self):
        self.assertEqual(self.check(installed="", installed_rc=1).severity, sr.Severity.SKIP)

    def test_skip_when_only_config_files_remain(self):
        # removed nginx ("rc") still reports a version
        finding = self.check(installed="1.30.6-1~trixie", state="rc")
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    def test_distro_nginx_warns(self):
        finding = self.check(installed="1.24.0-2ubuntu7")
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("distribution package", finding.detail)

    def test_ubuntu_leftover_fails_with_ups(self):
        self.write("etc/apt/sources.list.d/nginx.list.distUpgrade", LIST_MODERN)
        self.write("etc/apt/sources.list.d/nginx.list~", LIST_PLAIN)
        finding = self.check(installed="1.30.2-1~jammy")
        self.assertEqual((finding.severity, finding.fix), (sr.Severity.FAIL, "ups"))

    def test_wrong_codename_fails(self):
        self.write("etc/apt/sources.list.d/nginx.list", LIST_MODERN)
        self.assertEqual(self.check().severity, sr.Severity.FAIL)

    def test_disabled_deb822_fails(self):
        self.write("etc/apt/sources.list.d/nginx.sources", DEB822.replace("trixie", "noble") + "Enabled: no\n")
        self.assertEqual(self.check().severity, sr.Severity.FAIL)

    def test_ok_when_current(self):
        self.write("etc/apt/sources.list.d/nginx.list", GOOD)
        self.assertEqual(self.check().severity, sr.Severity.OK)

    def test_older_than_candidate_warns_with_ups(self):
        self.write("etc/apt/sources.list.d/nginx.list", GOOD)
        finding = self.check(installed="1.30.6-1~noble", newer=0)
        self.assertEqual((finding.severity, finding.fix), (sr.Severity.WARN, "ups"))

    def test_not_newer_candidate_is_ok(self):
        self.write("etc/apt/sources.list.d/nginx.list", GOOD)
        finding = self.check(installed="1.30.8-1~noble", newer=1)
        self.assertEqual(finding.severity, sr.Severity.OK)


@unittest.skipIf(sh is None, "needs PyYAML")
class HardeningConfigTest(unittest.TestCase):
    def test_content_has_nginx_origin_and_conffile_options(self):
        text = sh.unattended_override_content(False, "03:30")
        self.assertIn('Unattended-Upgrade::Origins-Pattern {', text)
        self.assertIn('"origin=nginx,codename=${distro_codename}";', text)
        self.assertIn('"--force-confdef";', text)
        self.assertIn('"--force-confold";', text)
        self.assertIn('Automatic-Reboot "false";', text)

    def test_reboot_settings_still_honoured(self):
        text = sh.unattended_override_content(True, "04:15")
        self.assertIn('Automatic-Reboot "true";', text)
        self.assertIn('Automatic-Reboot-Time "04:15";', text)

    def audit(self, installed, override_text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = sh.Path(tmp.name) / "52"
        if override_text is not None:
            override.write_text(override_text)
        buffer = io.StringIO()
        with mock.patch.object(sh, "UNATTENDED_OVERRIDE", override), \
                mock.patch.object(sh, "run", return_value=f"ii  {installed}" if installed else ""), \
                contextlib.redirect_stdout(buffer):
            sh.audit_auto_updates({"auto_updates": {}})
        return buffer.getvalue()

    def test_audit_fails_without_the_origin_when_nginx_org_is_installed(self):
        self.assertIn("nginx.org NICHT", self.audit("1.30.6-1~noble", "// old\n"))
        self.assertIn("nginx.org NICHT", self.audit("1.30.6-1~noble", None))

    def test_audit_ok_with_the_current_content(self):
        text = sh.unattended_override_content(False, "03:30")
        output = self.audit("1.30.6-1~noble", text)
        self.assertNotIn("nginx.org NICHT", output)
        self.assertIn("nginx.org als Quelle", output)

    def test_audit_silent_about_nginx_for_the_distro_package(self):
        output = self.audit("1.24.0-2ubuntu7", "// old\n")
        self.assertNotIn("nginx.org", output)


if __name__ == "__main__":
    unittest.main()
