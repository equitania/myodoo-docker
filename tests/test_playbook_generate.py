"""
Tests for Dockerfiles/playbooks/generate.py - the install_modules step and the
optional safety backup.

Run from the repository root:

    python3 -m unittest tests.test_playbook_generate -v
"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - depends on the machine
    raise unittest.SkipTest("PyYAML is not installed")

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "Dockerfiles", "playbooks", "generate.py")
spec = importlib.util.spec_from_file_location("playbook_generate", SOURCE)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

UPDATE = """\
containers:
  - container_name: live-odoo
    database_name: live_db
    install_modules: [eq_module_z]
  - container_name: test-odoo
    database_name: test_db
    volume: "-v /srv/test:/opt/odoo/data"
%s"""


class InstallModulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")

    def update_config(self, extra=""):
        path = os.path.join(self.tmp.name, "docker2update.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(UPDATE % extra)
        return path

    def run_generate(self, *argv):
        args = ["generate.py", "--version", "18", "--out", self.out,
                "--backup-config", "/nonexistent"] + list(argv)
        with mock.patch.object(sys, "argv", args), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return gen.main()

    def read(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as handle:
            return handle.read()

    def restore_playbooks(self):
        return [n for n in sorted(os.listdir(self.out)) if n != "passwoerter.yaml"]

    def test_without_modules_nothing_changes(self):
        self.run_generate("--no-detect")
        for name in os.listdir(self.out):
            text = self.read(name)
            self.assertNotIn("server.install", text, name)
            self.assertIn("Needs odoodev >= 0.75.7.", text, name)

    def test_the_modules_of_the_test_container_become_a_step_in_every_restore_playbook(self):
        config = self.update_config("    install_modules: [eq_module_a, eq_module_b]\n")
        self.run_generate("--update-config", config)
        names = self.restore_playbooks()
        self.assertEqual(len(names), len(gen.STATES))
        for name in names:
            text = self.read(name)
            step = ('  - name: "Install additional modules"\n'
                    "    command: server.install\n"
                    "    args:\n"
                    "      target: test\n"
                    "      modules: [eq_module_a, eq_module_b]\n")
            self.assertIn(step, text, name)
            self.assertLess(text.index("Neutralize (odoo-bin"), text.index(step), name)
            self.assertLess(text.index(step), text.index("Verify that the test instance"), name)
            self.assertIn("Needs odoodev >= 0.78.0.", text, name)
            self.assertIsInstance(yaml.safe_load(text), dict, name)
        self.assertNotIn("server.install", self.read("passwoerter.yaml"))
        self.assertIn("Needs odoodev >= 0.75.7.", self.read("passwoerter.yaml"))

    def test_the_modules_of_another_container_are_not_taken(self):
        config = self.update_config()
        self.run_generate("--update-config", config)
        self.assertNotIn("eq_module_z", "".join(self.read(n) for n in os.listdir(self.out)))

    def test_the_command_line_overrides_the_file(self):
        config = self.update_config("    install_modules: [eq_module_a]\n")
        self.run_generate("--update-config", config, "--install-modules", "eq_module_c, eq_module_d")
        text = self.read("neutral.yaml")
        self.assertIn("modules: [eq_module_c, eq_module_d]", text)
        self.assertNotIn("eq_module_a", text)

    def test_an_empty_command_line_value_switches_the_step_off(self):
        config = self.update_config("    install_modules: [eq_module_a]\n")
        self.run_generate("--update-config", config, "--install-modules", "")
        self.assertNotIn("server.install", self.read("neutral.yaml"))

    def test_an_invalid_module_name_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_generate("--no-detect", "--install-modules", "eq-module.a")



class SafetyBackupTest(unittest.TestCase):
    """A test instance is overwritten on every run: by default nothing is saved
    beforehand (8 GB a night that nobody prunes). --safety-backup brings back
    the copy and the playbook that restores it."""

    setUp = InstallModulesTest.setUp
    run_generate = InstallModulesTest.run_generate
    read = InstallModulesTest.read

    def test_by_default_no_playbook_saves_the_test_instance(self):
        self.run_generate("--no-detect")
        names = sorted(os.listdir(self.out))
        self.assertNotIn("wiederherstellen.yaml", names)
        self.assertEqual(len(names), len(gen.STATES) + 1)
        for name in names:
            text = self.read(name)
            self.assertNotIn("server.backup", text, name)
            self.assertNotIn("prerestore", text, name)
            self.assertIsInstance(yaml.safe_load(text), dict, name)
        steps = yaml.safe_load(self.read("neutral.yaml"))["steps"]
        self.assertEqual(steps[0]["command"], "container.stop")

    def test_safety_backup_saves_first_and_writes_the_restore_playbook(self):
        self.run_generate("--no-detect", "--safety-backup")
        for state in gen.STATES:
            steps = yaml.safe_load(self.read(f"{state}.yaml"))["steps"]
            self.assertEqual(steps[0]["command"], "server.backup", state)
            self.assertEqual(steps[0]["args"]["backup_dir"], gen.SAFETY_DIR, state)
        back = self.read("wiederherstellen.yaml")
        self.assertNotIn("server.backup", back)
        self.assertIn(f"dir: {gen.SAFETY_DIR}", back)

    def test_an_old_restore_playbook_is_reported_not_deleted(self):
        os.makedirs(self.out)
        stale = os.path.join(self.out, "wiederherstellen.yaml")
        with open(stale, "w", encoding="utf-8") as handle:
            handle.write("old\n")
        args = ["generate.py", "--version", "18", "--out", self.out, "--no-detect"]
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", args), contextlib.redirect_stdout(buffer):
            gen.main()
        self.assertIn("is from an earlier run with --safety-backup", buffer.getvalue())
        self.assertEqual(self.read("wiederherstellen.yaml"), "old\n")



class AfterRestoreSqlTest(unittest.TestCase):
    """Settings only the test instance needs (web.base.url, its FastReport token,
    an admin login) come from a root-only SQL file that odoodev reads at run time
    - never from the playbook itself."""

    setUp = InstallModulesTest.setUp
    run_generate = InstallModulesTest.run_generate
    read = InstallModulesTest.read

    def sql_file(self, mode=0o600):
        path = os.path.join(self.tmp.name, "after.sql")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("UPDATE res_users SET password = 'Xq7-marker-pw' WHERE id = 2;\n")
        os.chmod(path, mode)
        return path

    def test_without_the_file_there_is_no_step(self):
        self.run_generate("--no-detect")
        self.assertNotIn("sql.execute\n    args:\n      target: test\n      file:", self.read("neutral.yaml"))

    def test_the_file_runs_last_and_the_container_restarts(self):
        path = self.sql_file()
        self.run_generate("--no-detect", "--install-modules", "eq_module_a", "--after-restore-sql", path)
        for state in gen.STATES:
            steps = yaml.safe_load(self.read(f"{state}.yaml"))["steps"]
            commands = [step["command"] for step in steps]
            at = next(i for i, step in enumerate(steps) if step.get("args", {}).get("file") == path)
            self.assertGreater(at, commands.index("server.neutralize"), state)
            self.assertGreater(at, commands.index("server.install"), state)
            self.assertEqual(commands[at + 1:], ["container.stop", "container.start", "server.verify"], state)
        self.assertNotIn("Xq7-marker-pw", "".join(self.read(n) for n in os.listdir(self.out)))
        self.assertNotIn(path, self.read("passwoerter.yaml"))

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_generate("--no-detect", "--after-restore-sql", os.path.join(self.tmp.name, "absent.sql"))

    def test_a_file_readable_by_others_is_warned_about(self):
        path = self.sql_file(0o644)
        args = ["generate.py", "--version", "18", "--out", self.out, "--no-detect", "--after-restore-sql", path]
        err = io.StringIO()
        with mock.patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            gen.main()
        self.assertIn("chmod 600", err.getvalue())


if __name__ == "__main__":
    unittest.main()
