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
        message = re.search(r"FALLBACKS = \"\"\"\\?\n(.*?)\"\"\"",
                            source, re.DOTALL).group(1)
        for command in ("dostat", "wiz", "docron", "doval"):
            self.assertIn(command, message)

    def test_the_missing_library_message_points_at_ups_not_at_pip(self):
        """`pip install --user` is wrong on every server this runs on.

        Debian 12 and later refuse it outright (externally-managed-environment),
        and nothing else on an ownERP server is installed by hand. `ups` is the
        route; naming another sends an operator somewhere unmaintained. Read
        from the rendered message rather than the source, or the docstring
        explaining why pip is gone counts as pip being back.
        """
        if not HAVE_TEXTUAL:
            self.skipTest("needs the module importable")
        for found in (True, False):
            message = self.console.no_textual_message(uv_found=found)
            self.assertIn("ups", message)
            self.assertNotIn("pip install", message)

    def test_the_message_separates_a_missing_uv_from_an_unreachable_pypi(self):
        """Two different problems: one an update fixes, the other it cannot."""
        if not HAVE_TEXTUAL:
            self.skipTest("needs the module importable")
        without_uv = self.console.no_textual_message(uv_found=False)
        with_uv = self.console.no_textual_message(uv_found=True)
        self.assertIn("uv is missing", without_uv)
        self.assertIn("PyPI", with_uv)
        self.assertNotEqual(without_uv, with_uv)

    def test_a_failing_uv_run_falls_through_to_the_message(self):
        """uv explains what it could not download; it does not mention ups."""
        source = console_source()
        start = source.index("def _reexec_through_uv")
        body = source[start:source.index("\ntry:", start)]
        self.assertIn("if completed.returncode != 0:", body)

    def test_the_reexec_cannot_loop(self):
        """A guard variable, or a server spins up uv processes forever."""
        source = console_source()
        self.assertIn("OWNERP_CONSOLE_REEXEC", source)

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

    def save(self, kind, changes, index=0):
        async def body(app, pilot):
            app._save_changes(kind, index, changes)
            await pilot.pause()
        self.run_app(body)

    def test_a_backup_field_is_written_through_the_wizard(self):
        self.save(self.console.wizard.BACKUP, {"retention_days": 21})
        self.assertEqual(
            self.parsed("container2backup.yaml")["databases"][0]["retention_days"],
            21)

    def test_an_update_field_is_written_through_the_wizard(self):
        self.save(self.console.wizard.UPDATE, {"delay_time": 45})
        self.assertEqual(
            self.parsed("docker2update.yaml")["containers"][0]["delay_time"], 45)

    def test_a_whole_form_lands_in_one_write_with_one_backup(self):
        """The reason a form may replace field-at-a-time editing at all."""
        self.save(self.console.wizard.UPDATE,
                  {"delay_time": 45, "type": "M", "odoo_version": "19"})
        entry = self.parsed("docker2update.yaml")["containers"][0]
        self.assertEqual((entry["delay_time"], entry["type"]), (45, "M"))
        self.assertEqual(
            len([f for f in os.listdir(self.home) if ".bak-" in f]), 1)

    def test_a_write_leaves_a_backup_of_the_previous_content(self):
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            before = handle.read()
        self.save(self.console.wizard.BACKUP, {"retention_days": 21})
        backups = [f for f in os.listdir(self.home) if ".bak-" in f]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.home, backups[0]), encoding="utf-8") as h:
            self.assertEqual(h.read(), before)

    def test_a_rejected_value_is_refused_and_nothing_is_written(self):
        with open(os.path.join(self.home, "docker2update.yaml"),
                  encoding="utf-8") as handle:
            before = handle.read()
        self.save(self.console.wizard.UPDATE, {"type": "nonsense"})
        with open(os.path.join(self.home, "docker2update.yaml"),
                  encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual([f for f in os.listdir(self.home) if ".bak-" in f], [])

    def test_a_port_keeps_its_bind_address_when_changed(self):
        self.save(self.console.wizard.UPDATE, {"port": 19000})
        self.assertEqual(self.parsed("docker2update.yaml")["containers"][0]["port"],
                         "127.0.0.1:19000")

    def test_the_table_reflects_the_change_afterwards(self):
        """A write that does not refresh the view invites a second one."""
        async def body(app, pilot):
            app._save_changes(self.console.wizard.BACKUP, 0,
                              {"retention_days": 21})
            await pilot.pause()
            return app.query_one("#backup", self.console.DataTable).get_row_at(0)
        self.assertIn("21", str(self.run_app(body)))

    def test_a_toggle_flips_the_stored_value(self):
        async def body(app, pilot):
            app._toggle(self.console.wizard.UPDATE, 0, "active",
                        "Take part in updates")
            await pilot.pause()
        self.run_app(body)
        self.assertIs(
            self.parsed("docker2update.yaml")["containers"][0]["active"], False)

    def test_a_toggle_inserts_the_field_when_it_is_absent(self):
        """only_sql_dump is not in the shipped backup entry."""
        async def body(app, pilot):
            app._toggle(self.console.wizard.BACKUP, 0, "only_sql_dump",
                        "Database only")
            await pilot.pause()
        self.run_app(body)
        self.assertIs(
            self.parsed("container2backup.yaml")["databases"][0]["only_sql_dump"],
            True)

    def test_an_empty_change_set_writes_nothing(self):
        async def body(app, pilot):
            app._save_changes(self.console.wizard.BACKUP, 0, {})
            await pilot.pause()
        self.run_app(body)
        self.assertEqual([f for f in os.listdir(self.home) if ".bak-" in f], [])


class MenuTest(ConsoleFixture):
    """Selecting a row offers what that tab can do with it."""

    def test_selecting_an_instance_row_opens_the_menu(self):
        async def body(app, pilot):
            app.query_one("#instances", self.console.DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            return type(app.screen).__name__
        self.assertEqual(self.run_app(body), "ActionMenu")

    def test_the_menu_offers_edit_new_and_a_toggle(self):
        names = [name for _key, _label, name in
                 load_console().Console.ACTIONS["backup"]]
        self.assertEqual(names, ["edit", "new", "toggle-sql", "cancel"])

    def test_a_letter_picks_its_action(self):
        async def body(app, pilot):
            app.query_one("#backup", self.console.DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            return type(app.screen).__name__
        self.assertEqual(self.run_app(body), "EntryForm")

    def test_cancel_closes_the_menu_without_a_form(self):
        async def body(app, pilot):
            app.query_one("#backup", self.console.DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            return type(app.screen).__name__
        self.assertNotIn(self.run_app(body), ("ActionMenu", "EntryForm"))

    def test_the_system_tab_has_no_actions(self):
        """Readiness findings are facts, not settings."""
        self.assertNotIn("system", load_console().Console.ACTIONS)

    def test_no_label_is_wider_than_the_box(self):
        """The menu clips rather than wraps, and a clipped label misleads.

        "[s] database only, no filest" is not a shorter way of saying the same
        thing - it is a different sentence, and it was on screen.
        """
        console = load_console()
        for table, actions in console.Console.ACTIONS.items():
            for key, label, _name in actions:
                self.assertLessEqual(len(f"[{key}] {label}"),
                                     console.MENU_LABEL_WIDTH,
                                     f"{table}: {label}")

    def test_the_key_letters_survive_rendering(self):
        """"[e]" is valid Rich markup for a style tag.

        Rendered with markup on, every line loses its key and the menu becomes
        a list of things you cannot reach by keyboard. Asserting on ACTIONS
        alone would never have caught it - this reads what is on screen.
        """
        async def body(app, pilot):
            app.query_one("#backup", self.console.DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            return [str(label.render()) for label in
                    app.screen.query(self.console.Label)]
        rendered = " ".join(self.run_app(body))
        for key in ("[e]", "[n]", "[s]", "[c]"):
            self.assertIn(key, rendered)


class FormTest(ConsoleFixture):
    """The form itself: what it renders, and what it hands back."""

    def form_for(self, kind, index=0):
        """Open the real form over the real configuration."""
        async def body(app, pilot):
            app._open_form(kind, index)
            await pilot.pause()
            return app.screen
        return body

    def test_a_boolean_field_is_a_switch_not_a_text_box(self):
        async def body(app, pilot):
            app._open_form(self.console.wizard.BACKUP, 0)
            await pilot.pause()
            return type(app.screen.query_one("#f-only_sql_dump")).__name__
        self.assertEqual(self.run_app(body), "Switch")

    def test_the_password_field_starts_empty_and_is_masked(self):
        async def body(app, pilot):
            app._open_form(self.console.wizard.UPDATE, 0)
            await pilot.pause()
            widget = app.screen.query_one("#f-db_password")
            return widget.value, widget.password
        value, masked = self.run_app(body)
        self.assertEqual(value, "")
        self.assertTrue(masked)

    def test_an_untouched_form_reports_no_changes(self):
        async def body(app, pilot):
            app._open_form(self.console.wizard.UPDATE, 0)
            await pilot.pause()
            screen = app.screen
            screen.action_save()
            await pilot.pause()
            return screen.query("#f-db_password")
        self.run_app(body)
        # Nothing written means no backup file, and above all no password
        # rewritten from a masked placeholder.
        self.assertEqual([f for f in os.listdir(self.home) if ".bak-" in f], [])
        self.assertEqual(self.parsed("docker2update.yaml")["containers"][0]
                         ["db_password"], "secret")

    def test_a_changed_field_is_written_end_to_end(self):
        async def body(app, pilot):
            app._open_form(self.console.wizard.BACKUP, 0)
            await pilot.pause()
            app.screen.query_one("#f-retention_days").value = "21"
            app.screen.action_save()
            await pilot.pause()
        self.run_app(body)
        self.assertEqual(
            self.parsed("container2backup.yaml")["databases"][0]["retention_days"],
            21)

    def test_a_non_numeric_value_never_reaches_the_file(self):
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            before = handle.read()

        async def body(app, pilot):
            app._open_form(self.console.wizard.BACKUP, 0)
            await pilot.pause()
            app.screen.query_one("#f-retention_days").value = "not-a-number"
            app.screen.action_save()
            await pilot.pause()
            return type(app.screen).__name__
        self.assertEqual(self.run_app(body), "EntryForm")
        with open(os.path.join(self.home, "container2backup.yaml"),
                  encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_every_form_field_carries_its_help_text(self):
        """The prompt wizard printed it per question; losing it is a regression."""
        console = load_console()
        for kind in (console.wizard.UPDATE, console.wizard.BACKUP):
            for field in console.wizard.KINDS[kind]["form"]:
                self.assertTrue(field.help, f"{kind}.{field.name}")


class NewEntryTest(ConsoleFixture):
    """Adding an entry, and the suggestions that make it bearable."""

    def test_suggestions_fill_what_can_be_known_before_the_name(self):
        console = load_console()
        entries = [{"container_name": "test-odoo", "db_user": "ownerp",
                    "port": "127.0.0.1:13000",
                    "longpolling_port": "127.0.0.1:14000",
                    "dockerfile_path": "/root/docker-builds/test-odoo/",
                    "docker_image_name": "odoo/test"}]
        suggested = console._suggested(console.wizard.UPDATE, entries)
        self.assertEqual(suggested["db_user"], "ownerp")
        self.assertIn("port", suggested)

    def test_the_build_folder_follows_the_name_the_operator_typed(self):
        """Suggested after the form closes - at open time there was no name."""
        console = load_console()
        entries = [{"container_name": "test-odoo",
                    "dockerfile_path": "/root/docker-builds/test-odoo/",
                    "docker_image_name": "odoo/test"}]
        entry = console._complete(console.wizard.UPDATE, entries,
                                  {"container_name": "shop-odoo",
                                   "database_name": "shop_db"})
        self.assertEqual(entry["dockerfile_path"],
                         "/root/docker-builds/shop-odoo/")
        self.assertEqual(entry["docker_image_name"], "odoo/shop")

    def test_a_blank_field_is_dropped_rather_than_written_empty(self):
        console = load_console()
        entry = console._complete(console.wizard.BACKUP, [],
                                  {"name": "shop_db", "db_user": ""})
        self.assertEqual(entry["name"], "shop_db")
        self.assertNotIn("db_user", entry)

    def test_a_new_entry_asks_before_it_writes(self):
        async def body(app, pilot):
            app._create(self.console.wizard.BACKUP, [], {"name": "shop_db"})
            await pilot.pause()
            return type(app.screen).__name__
        self.assertEqual(self.run_app(body), "Confirm")
        self.assertEqual([f for f in os.listdir(self.home) if ".bak-" in f], [])

    def test_a_confirmed_new_entry_reaches_the_file(self):
        async def body(app, pilot):
            app._write_new(self.console.wizard.BACKUP,
                           {"name": "shop_db", "sql_container": "shop-db",
                            "data_container": "shop-odoo"})
            await pilot.pause()
        self.run_app(body)
        names = [d["name"] for d in
                 self.parsed("container2backup.yaml")["databases"]]
        self.assertIn("shop_db", names)


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
