"""
Tests for ownerp_console.py — stage 3 of the console design.

Split in two deliberately. The checks that need no Textual always run: the
refusals, the dependency list, and the rule that the console owns no write
path of its own. Those are the ones that must not rot on a machine without the
library, and they cover the two defects that would actually reach a customer.

The interface tests need Textual and skip without it. They drive the real
application through Textual's own test pilot, against a throwaway $HOME.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_console -v

With Textual available:

    uv run --with 'textual>=8,<9' --with pyyaml python3 -m unittest \\
        tests.test_ownerp_console -v
"""

import asyncio
import importlib.util
import os
import re
import shutil
import tempfile
import time
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")
CONSOLE = os.path.join(SCRIPTS, "ownerp_console.py")

try:
    import textual  # noqa: F401
    HAVE_TEXTUAL = True
except ImportError:
    HAVE_TEXTUAL = False

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def load_console():
    spec = importlib.util.spec_from_file_location("ownerp_console", CONSOLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def console_source():
    with open(CONSOLE, encoding="utf-8") as handle:
        return handle.read()


# ==============================================================================
# Always run: these are the ones that reach a customer when they are wrong
# ==============================================================================

class DependencyTest(unittest.TestCase):
    """`uv run --with` builds an ISOLATED environment.

    The console re-executes itself through uv when Textual is missing. That
    environment does not see the system site-packages, so a dependency left
    off this list is simply absent at runtime — and PyYAML being absent makes
    every section of the report read "unknown", which looks exactly like a
    broken server. It cost a live run to find; this keeps it found.
    """

    def test_pyyaml_is_declared_alongside_textual(self):
        source = console_source()
        match = re.search(r"DEPENDENCIES = \((.*?)\)", source, re.DOTALL)
        self.assertIsNotNone(match, "DEPENDENCIES is no longer a literal tuple")
        self.assertIn("YAML_SPEC", match.group(1))
        self.assertIn("TEXTUAL_SPEC", match.group(1))

    def test_every_declared_dependency_is_passed_to_uv(self):
        """A spec in the list that the re-exec does not pass is decoration."""
        source = console_source()
        self.assertIn("for spec in DEPENDENCIES", source)

    def test_textual_is_pinned_to_a_major_version(self):
        source = console_source()
        self.assertRegex(source, r'TEXTUAL_SPEC = "textual>=\d+,<\d+"')


class OwnershipTest(unittest.TestCase):
    """The console renders and delegates. It owns no data and no write path."""

    def test_it_never_writes_a_configuration_itself(self):
        source = console_source()
        for forbidden in ("os.replace(", "shutil.copy", "open(path, \"w\")",
                          "os.remove("):
            self.assertNotIn(forbidden, source,
                             "configuration changes belong to ownerp_wizard.py")

    def test_it_starts_no_updates_and_no_backups(self):
        """The boundary that lets it skip process supervision entirely."""
        source = console_source()
        for forbidden in ("update_docker_odoo", "container2backup",
                          "docker restart", "docker run"):
            if forbidden == "container2backup":
                # The filename appears as a path to READ; a call would not.
                self.assertNotIn("container2backup.py", source)
                continue
            self.assertNotIn(forbidden, source)

    def test_the_cron_is_changed_through_ownerp_cron_only(self):
        source = console_source()
        self.assertIn("cron.write(", source)
        self.assertNotIn("/etc/cron.d/myodoo-maintenance", source)


class RefusalTest(unittest.TestCase):
    """A refusal names what does work. Being told 'no' is half an answer."""

    def setUp(self):
        self.console = load_console() if HAVE_TEXTUAL else None

    def test_no_terminal_is_refused_and_points_at_dostat(self):
        if not HAVE_TEXTUAL:
            self.skipTest("needs the module importable")
        reason = self.console.preflight(is_tty=False, stdin_tty=True, term="xterm")
        self.assertIn("dostat", reason)

    def test_a_dumb_terminal_is_refused_and_points_at_dostat(self):
        if not HAVE_TEXTUAL:
            self.skipTest("needs the module importable")
        reason = self.console.preflight(is_tty=True, stdin_tty=True, term="dumb")
        self.assertIn("dostat", reason)

    def test_a_real_terminal_is_accepted(self):
        if not HAVE_TEXTUAL:
            self.skipTest("needs the module importable")
        self.assertIsNone(self.console.preflight(
            is_tty=True, stdin_tty=True, term="xterm-256color"))

    def test_the_missing_library_message_names_all_four_fallbacks(self):
        """Read from the source, so it holds even without Textual installed."""
        source = console_source()
        message = re.search(r"NO_TEXTUAL = f?\"\"\"\\?\n(.*?)\"\"\"",
                            source, re.DOTALL).group(1)
        for command in ("dostat", "wiz", "docron", "doval"):
            self.assertIn(command, message)

    def test_the_reexec_cannot_loop(self):
        """A guard variable, or a server spins up uv processes forever."""
        source = console_source()
        self.assertIn("OWNERP_CONSOLE_REEXEC", source)


# ==============================================================================
# Interface: needs Textual
# ==============================================================================

UPDATE_CONFIG = """\
containers:
  - active: true
    type: F
    delay_time: 10
    container_name: test-odoo
    database_name: test_db
    port: "127.0.0.1:13000"
    longpolling_port: "127.0.0.1:14000"
    dockerfile_path: /root/docker-builds/test-odoo/
    docker_image_name: odoo/test
    db_user: ownerp
    db_password: secret
    db_host: test-db
    volume: "-v /opt/odoo/test:/opt/odoo/data"
    odoo_version: "16"
    translate: Y
"""

BACKUP_CONFIG = """\
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: {path}
databases:
  - name: test_db
    sql_container: test-db
    data_container: test-odoo
"""


@unittest.skipUnless(HAVE_TEXTUAL and HAVE_YAML, "needs Textual and PyYAML")
class ConsoleFixture(unittest.TestCase):
    def setUp(self):
        self.console = load_console()
        self.home = tempfile.mkdtemp(prefix="ownerp-console-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.backup_path = os.path.join(self.home, "backups")
        os.makedirs(os.path.join(self.backup_path, "docker"))
        self.write("docker2update.yaml", UPDATE_CONFIG)
        self.write("container2backup.yaml",
                   BACKUP_CONFIG.format(path=self.backup_path))
        self.archive()

    def write(self, name, text):
        with open(os.path.join(self.home, name), "w", encoding="utf-8") as h:
            h.write(text)

    def archive(self, age_hours=3.0):
        path = os.path.join(self.backup_path, "docker",
                            "test_db_test-odoo_dockerbackup_20260813_020000.7z")
        with open(path, "wb") as handle:
            handle.write(b"\0" * 4096)
        when = time.time() - age_hours * 3600
        os.utime(path, (when, when))

    def parsed(self, name):
        with open(os.path.join(self.home, name), encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def run_app(self, body):
        """Drive the real application through Textual's pilot."""
        async def go():
            app = self.console.Console(home=self.home)
            async with app.run_test(size=(110, 34)) as pilot:
                await pilot.pause()
                return await body(app, pilot)
        return asyncio.run(go())


class TablesTest(ConsoleFixture):
    def test_every_section_is_populated(self):
        def check(app, _pilot):
            counts = {}
            for name in ("instances", "backup", "maintenance", "system"):
                counts[name] = app.query_one(f"#{name}",
                                             self.console.DataTable).row_count
            return counts

        async def body(app, pilot):
            return check(app, pilot)
        counts = self.run_app(body)
        self.assertEqual(counts["instances"], 1)
        self.assertEqual(counts["backup"], 1)
        self.assertGreater(counts["system"], 0)

    def test_the_backup_row_shows_the_archive_it_found(self):
        async def body(app, _pilot):
            return app.query_one("#backup", self.console.DataTable).get_row_at(0)
        row = self.run_app(body)
        self.assertEqual(row[0], "ok")
        self.assertIn("test_db", row[1])
        self.assertIn("ago", row[2])

    def test_an_instance_without_docker_reads_as_unknown_not_down(self):
        async def body(app, _pilot):
            return app.query_one("#instances",
                                 self.console.DataTable).get_row_at(0)
        self.assertEqual(self.run_app(body)[0], "?")

    def test_reload_does_not_duplicate_rows(self):
        async def body(app, pilot):
            app.action_reload()
            await pilot.pause()
            return app.query_one("#backup", self.console.DataTable).row_count
        self.assertEqual(self.run_app(body), 1)

    def test_a_broken_configuration_costs_one_section_not_the_console(self):
        self.write("docker2update.yaml", "containers: [unclosed\n")

        async def body(app, _pilot):
            instances = app.query_one("#instances", self.console.DataTable)
            backup = app.query_one("#backup", self.console.DataTable)
            return instances.get_row_at(0), backup.get_row_at(0)
        broken, healthy = self.run_app(body)
        self.assertEqual(broken[0], "?")
        self.assertEqual(healthy[0], "ok")


class WriteTest(ConsoleFixture):
    """Every change goes through ownerp_wizard, and is visible on disk."""

    def field(self, kind, name):
        return [f for f in self.console.wizard.KINDS[kind]["form"]
                if f.name == name][0]

    def test_a_backup_field_is_written_through_the_wizard(self):
        async def body(app, pilot):
            app._write_field(self.console.wizard.BACKUP, 0,
                             self.field(self.console.wizard.BACKUP,
                                        "retention_days"), "21")
            await pilot.pause()
        self.run_app(body)
        self.assertEqual(
            self.parsed("container2backup.yaml")["databases"][0]["retention_days"],
            21)

    def test_an_update_field_is_written_through_the_wizard(self):
        async def body(app, pilot):
            app._write_field(self.console.wizard.UPDATE, 0,
                             self.field(self.console.wizard.UPDATE,
                                        "delay_time"), "45")
            await pilot.pause()
        self.run_app(body)
        self.assertEqual(
            self.parsed("docker2update.yaml")["containers"][0]["delay_time"], 45)

    def test_a_write_leaves_a_backup_of_the_previous_content(self):
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            before = handle.read()

        async def body(app, pilot):
            app._write_field(self.console.wizard.BACKUP, 0,
                             self.field(self.console.wizard.BACKUP,
                                        "retention_days"), "21")
            await pilot.pause()
        self.run_app(body)
        backups = [f for f in os.listdir(self.home) if ".bak-" in f]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.home, backups[0]), encoding="utf-8") as h:
            self.assertEqual(h.read(), before)

    def test_a_non_numeric_value_is_refused_and_nothing_is_written(self):
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            before = handle.read()

        async def body(app, pilot):
            app._write_field(self.console.wizard.BACKUP, 0,
                             self.field(self.console.wizard.BACKUP,
                                        "retention_days"), "not-a-number")
            await pilot.pause()
        self.run_app(body)
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual([f for f in os.listdir(self.home) if ".bak-" in f], [])

    def test_a_port_keeps_its_bind_address_when_changed(self):
        async def body(app, pilot):
            app._write_field(self.console.wizard.UPDATE, 0,
                             self.field(self.console.wizard.UPDATE, "port"),
                             "19000")
            await pilot.pause()
        self.run_app(body)
        self.assertEqual(self.parsed("docker2update.yaml")["containers"][0]["port"],
                         "127.0.0.1:19000")

    def test_the_table_reflects_the_change_afterwards(self):
        """A write that does not refresh the view invites a second one."""
        async def body(app, pilot):
            app._write_field(self.console.wizard.BACKUP, 0,
                             self.field(self.console.wizard.BACKUP,
                                        "retention_days"), "21")
            await pilot.pause()
            return app.query_one("#backup", self.console.DataTable).get_row_at(0)
        self.assertIn("21", str(self.run_app(body)))


class NavigationTest(ConsoleFixture):
    def test_the_tabs_are_all_present(self):
        async def body(app, _pilot):
            tabs = app.query_one("#tabs", self.console.TabbedContent)
            return [pane.id for pane in tabs.query(self.console.TabPane)]
        panes = self.run_app(body)
        for expected in ("tab-overview", "tab-instances", "tab-backup",
                         "tab-maintenance", "tab-system"):
            self.assertIn(expected, panes)

    def test_the_overview_tiles_are_built(self):
        async def body(app, _pilot):
            return len(app.query_one("#tiles", self.console.Grid).children)
        self.assertEqual(self.run_app(body), 4)

    def test_the_subtitle_carries_the_worst_severity(self):
        async def body(app, _pilot):
            return app.sub_title
        self.assertRegex(self.run_app(body), r"(OK|WARN|FAIL)")


if __name__ == "__main__":
    unittest.main()
