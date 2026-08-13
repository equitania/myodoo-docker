"""
Tests for ownerp_state.py — the server state collector behind `dostat`.

The weight is on the failure paths, because that is what the module is for. A
status tool is read on a broken server: docker down, PyYAML missing, a YAML
that does not parse, /etc unreadable. Each of those must cost exactly one
section and leave the rest of the page standing. A traceback is never the right
answer to "what is wrong with this machine".

Run from the repository root:

    python3 -m unittest tests.test_ownerp_state -v
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import time
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")

_spec = importlib.util.spec_from_file_location(
    "ownerp_state", os.path.join(SCRIPTS, "ownerp_state.py"))
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


UPDATE_CONFIG = """\
containers:
  - container_name: live-odoo
    database_name: live_db
    odoo_version: "16"
    type: F
  - container_name: test-odoo
    database_name: test_db
    odoo_version: "16"
    active: false
"""

BACKUP_CONFIG = """\
defaults:
  retention_days: 14
  backup_path: {path}
databases:
  - name: live_db
    sql_container: live-db
    data_container: live-odoo
  - name: test_db
    sql_container: test-db
    data_container: test-odoo
    only_sql_dump: true
"""


class StateFixture(unittest.TestCase):
    """A throwaway $HOME with both configurations and a backup directory."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ownerp-state-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.backup_path = os.path.join(self.home, "backups")
        os.makedirs(os.path.join(self.backup_path, "docker"))

    def write(self, name, text):
        path = os.path.join(self.home, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_configs(self):
        self.write(st.UPDATE_YAML, UPDATE_CONFIG)
        self.write(st.BACKUP_YAML, BACKUP_CONFIG.format(path=self.backup_path))

    def archive(self, database, container, age_hours=1.0, size=2048,
                suffix=".7z"):
        """Put one backup archive on disk with a chosen age."""
        name = f"{database}_{container}_dockerbackup_20260813_020000{suffix}"
        path = os.path.join(self.backup_path, "docker", name)
        with open(path, "wb") as handle:
            handle.write(b"\0" * size)
        when = time.time() - age_hours * 3600
        os.utime(path, (when, when))
        return path


@unittest.skipUnless(HAVE_YAML, "the collectors read YAML")
class InstanceCollectionTest(StateFixture):
    def setUp(self):
        super().setUp()
        self.write_configs()

    def test_entries_come_from_the_configuration(self):
        result = st.collect_instances(self.home, docker=False)
        self.assertIsNone(result.error)
        self.assertEqual([i.name for i in result.entries],
                         ["live-odoo", "test-odoo"])

    def test_an_inactive_entry_is_kept_and_marked(self):
        """Dropping it would hide a system somebody parked on purpose."""
        result = st.collect_instances(self.home, docker=False)
        by_name = {i.name: i for i in result.entries}
        self.assertTrue(by_name["live-odoo"].active)
        self.assertFalse(by_name["test-odoo"].active)

    def test_container_state_is_unknown_rather_than_down_without_docker(self):
        """`running=False` would claim a fact nobody established."""
        result = st.collect_instances(self.home, docker=False)
        self.assertTrue(all(i.running is None for i in result.entries))

    def test_a_missing_configuration_is_a_sentence_not_an_exception(self):
        os.remove(os.path.join(self.home, st.UPDATE_YAML))
        result = st.collect_instances(self.home, docker=False)
        self.assertIn("not found", result.error)
        self.assertEqual(result.entries, [])

    def test_a_broken_configuration_names_its_line(self):
        self.write(st.UPDATE_YAML, "containers:\n  - name: [unclosed\n")
        result = st.collect_instances(self.home, docker=False)
        self.assertIn("does not parse", result.error)

    def test_a_container_entry_that_is_not_a_mapping_is_skipped(self):
        self.write(st.UPDATE_YAML,
                   "containers:\n  - just-a-string\n"
                   "  - container_name: live-odoo\n")
        result = st.collect_instances(self.home, docker=False)
        self.assertEqual([i.name for i in result.entries], ["live-odoo"])


@unittest.skipUnless(HAVE_YAML, "the collectors read YAML")
class BackupCollectionTest(StateFixture):
    def setUp(self):
        super().setUp()
        self.write_configs()

    def test_archives_are_matched_to_their_database(self):
        self.archive("live_db", "live-odoo")
        result = st.collect_backups(self.home)
        by_db = {b.database: b for b in result.entries}
        self.assertEqual(len(by_db["live_db"].archives), 1)
        self.assertEqual(by_db["test_db"].archives, [])

    def test_the_newest_archive_wins(self):
        self.archive("live_db", "live-odoo", age_hours=40, size=100)
        self.archive("live_db", "live-odoo", age_hours=2, size=999,
                     suffix=".tar.zst")
        entry = st.collect_backups(self.home).entries[0]
        self.assertEqual(entry.newest.size, 999)
        self.assertEqual(len(entry.archives), 2)

    def test_a_database_without_an_archive_is_a_failure(self):
        """The configuration promises a backup; the disk does not have one."""
        entry = st.collect_backups(self.home).entries[0]
        self.assertEqual(entry.severity, "FAIL")

    def test_a_stale_archive_warns_before_it_fails(self):
        self.archive("live_db", "live-odoo", age_hours=30)
        entry = st.collect_backups(self.home).entries[0]
        self.assertEqual(entry.severity, "WARN")

    def test_a_fresh_archive_is_ok(self):
        self.archive("live_db", "live-odoo", age_hours=3)
        entry = st.collect_backups(self.home).entries[0]
        self.assertEqual(entry.severity, "OK")

    def test_another_database_from_the_same_container_stays_apart(self):
        """The stem carries both names, so the two never blur together."""
        self.archive("live_db", "live-odoo")
        self.archive("test_db", "test-odoo")
        by_db = {b.database: b for b in st.collect_backups(self.home).entries}
        self.assertEqual(len(by_db["live_db"].archives), 1)
        self.assertEqual(len(by_db["test_db"].archives), 1)

    def test_a_file_that_is_not_an_archive_is_ignored(self):
        folder = os.path.join(self.backup_path, "docker")
        with open(os.path.join(folder, "live_db_live-odoo_dockerbackup_x.log"),
                  "w", encoding="utf-8") as handle:
            handle.write("not an archive")
        self.assertEqual(st.collect_backups(self.home).entries[0].archives, [])

    def test_retention_falls_back_to_the_defaults_block(self):
        by_db = {b.database: b for b in st.collect_backups(self.home).entries}
        self.assertEqual(by_db["live_db"].retention_days, 14)

    def test_the_backup_path_comes_from_the_configuration(self):
        self.assertEqual(st.collect_backups(self.home).backup_path,
                         self.backup_path)

    def test_a_missing_backup_configuration_is_reported_not_raised(self):
        os.remove(os.path.join(self.home, st.BACKUP_YAML))
        result = st.collect_backups(self.home)
        self.assertIn("not found", result.error)


class DiskTest(StateFixture):
    def test_a_real_path_measures(self):
        disk = st.disk_usage(self.home)
        self.assertIsNotNone(disk)
        self.assertGreater(disk.total, 0)
        self.assertIn(disk.severity, ("OK", "WARN", "FAIL"))

    def test_a_missing_path_is_none_not_an_exception(self):
        self.assertIsNone(st.disk_usage(os.path.join(self.home, "nope")))

    def test_percentages_map_to_severities(self):
        self.assertEqual(st.Disk("/", 100, 50, 50).severity, "OK")
        self.assertEqual(st.Disk("/", 100, 88, 12).severity, "WARN")
        self.assertEqual(st.Disk("/", 100, 97, 3).severity, "FAIL")

    def test_an_unmeasurable_disk_does_not_divide_by_zero(self):
        self.assertEqual(st.Disk("/", 0, 0, 0).percent_used, 0)
        self.assertEqual(st.Disk("/", 0, 0, 0).severity, "SKIP")


class HistoryTest(StateFixture):
    def test_the_newest_run_per_container_wins(self):
        with open(os.path.join(self.home, st.HISTORY_FILE), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps({"container": "live-odoo",
                                     "ts": "2026-08-01T10:00:00",
                                     "result": "ok"}) + "\n")
            handle.write(json.dumps({"container": "live-odoo",
                                     "ts": "2026-08-12T10:00:00",
                                     "result": "failed"}) + "\n")
        latest = st.read_history(self.home)
        self.assertEqual(latest["live-odoo"]["result"], "failed")

    def test_a_torn_line_does_not_lose_the_rest_of_the_file(self):
        """History is appended to while a run is in flight."""
        with open(os.path.join(self.home, st.HISTORY_FILE), "w",
                  encoding="utf-8") as handle:
            handle.write('{"container": "live-odoo", "ts": "2026-08-01T10:00:00"}\n')
            handle.write('{"container": "test-odoo", "ts": "2026-0\n')
        latest = st.read_history(self.home)
        self.assertIn("live-odoo", latest)

    def test_no_history_is_normal_not_an_error(self):
        self.assertEqual(st.read_history(self.home), {})

    def test_a_run_without_history_renders_as_never(self):
        self.assertEqual(st.Instance("live-odoo").last_run_text, "never")

    def test_an_unparseable_timestamp_does_not_raise(self):
        entry = st.Instance("x", last_run={"ts": "nonsense", "mode": "F",
                                           "result": "ok"})
        self.assertIn("?", entry.last_run_text)


class DockerTest(unittest.TestCase):
    def setUp(self):
        self.original = shutil.which
        self.addCleanup(lambda: setattr(shutil, "which", self.original))

    def test_a_missing_docker_is_named_not_raised(self):
        shutil.which = lambda name: None
        status, error = st.docker_status()
        self.assertEqual(status, {})
        self.assertIn("not installed", error)

    def test_a_timeout_is_reported_as_one(self):
        """A hung daemon must not hang the report."""
        import subprocess
        shutil.which = lambda name: "/usr/bin/docker"
        original_run = subprocess.run

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

        subprocess.run = timeout
        self.addCleanup(lambda: setattr(subprocess, "run", original_run))
        status, error = st.docker_status(timeout=1)
        self.assertEqual(status, {})
        self.assertIn("did not answer", error)


@unittest.skipUnless(HAVE_YAML, "the report needs the collectors")
class RenderTest(StateFixture):
    def setUp(self):
        super().setUp()
        self.write_configs()
        self.archive("live_db", "live-odoo", age_hours=2)

    def state(self):
        return st.ServerState(
            hostname="ucore",
            collected_at=time.time(),
            instances=st.collect_instances(self.home, docker=False),
            backups=st.collect_backups(self.home),
            maintenance=st.Maintenance("maintenance", error="not installed"),
            health=st.Health("health", error="skipped"),
        )

    def text(self, **kwargs):
        stream = io.StringIO()
        st.render(self.state(), stream=stream, **kwargs)
        return stream.getvalue()

    def test_every_section_appears_even_when_two_are_unknown(self):
        text = self.text()
        for heading in ("Instances", "Backup", "Maintenance", "System"):
            self.assertIn(heading, text)

    def test_an_unknown_section_states_its_reason(self):
        self.assertIn("not installed", self.text())

    def test_the_hostname_is_in_the_header(self):
        self.assertIn("ucore", self.text())

    def test_a_database_without_a_backup_is_visible_in_the_text(self):
        self.assertIn("no archive found", self.text())

    def test_nothing_is_coloured_when_the_output_is_not_a_terminal(self):
        """dostat lands in mails and log files."""
        self.assertNotIn("\033[", self.text())


@unittest.skipUnless(HAVE_YAML, "the summary reads collected entries")
class WorstTest(StateFixture):
    def setUp(self):
        super().setUp()
        self.write_configs()

    def state(self, **kwargs):
        base = dict(instances=st.Instances("instances"),
                    backups=st.collect_backups(self.home),
                    maintenance=st.Maintenance("maintenance"),
                    health=st.Health("health"))
        base.update(kwargs)
        return st.ServerState(**base)

    def test_a_missing_backup_makes_the_whole_report_fail(self):
        self.assertEqual(st.worst(self.state()), "FAIL")

    def test_a_stale_backup_warns(self):
        self.archive("live_db", "live-odoo", age_hours=30)
        self.archive("test_db", "test-odoo", age_hours=3)
        self.assertEqual(st.worst(self.state()), "WARN")

    def test_everything_fresh_is_ok(self):
        self.archive("live_db", "live-odoo", age_hours=2)
        self.archive("test_db", "test-odoo", age_hours=2)
        self.assertEqual(st.worst(self.state()), "OK")

    def test_a_stopped_active_container_fails(self):
        instances = st.Instances("instances", entries=[
            st.Instance("live-odoo", active=True, running=False)])
        self.archive("live_db", "live-odoo", age_hours=2)
        self.archive("test_db", "test-odoo", age_hours=2)
        self.assertEqual(st.worst(self.state(instances=instances)), "FAIL")

    def test_a_stopped_inactive_container_does_not(self):
        """Parked on purpose is not a fault."""
        instances = st.Instances("instances", entries=[
            st.Instance("test-odoo", active=False, running=False)])
        self.archive("live_db", "live-odoo", age_hours=2)
        self.archive("test_db", "test-odoo", age_hours=2)
        self.assertEqual(st.worst(self.state(instances=instances)), "OK")

    def test_an_unknown_container_state_is_not_treated_as_down(self):
        instances = st.Instances("instances", entries=[
            st.Instance("live-odoo", active=True, running=None)])
        self.archive("live_db", "live-odoo", age_hours=2)
        self.archive("test_db", "test-odoo", age_hours=2)
        self.assertEqual(st.worst(self.state(instances=instances)), "OK")


@unittest.skipUnless(HAVE_YAML, "the json mirrors the collected state")
class JsonTest(StateFixture):
    def setUp(self):
        super().setUp()
        self.write_configs()
        self.archive("live_db", "live-odoo", age_hours=2)

    def test_the_json_parses_and_carries_every_section(self):
        state = st.ServerState(
            hostname="ucore",
            instances=st.collect_instances(self.home, docker=False),
            backups=st.collect_backups(self.home),
            maintenance=st.Maintenance("maintenance", error="not installed"),
            health=st.Health("health"))
        data = json.loads(st.as_json(state))
        self.assertEqual(data["hostname"], "ucore")
        self.assertEqual(len(data["instances"]["entries"]), 2)
        self.assertEqual(data["maintenance"]["error"], "not installed")

    def test_an_error_survives_into_the_json(self):
        state = st.ServerState(backups=st.Backups("backups", error="gone"))
        self.assertEqual(json.loads(st.as_json(state))["backups"]["error"],
                         "gone")


class FormattingTest(unittest.TestCase):
    def test_sizes_read_at_a_glance(self):
        self.assertEqual(st.human_size(512), "512B")
        self.assertEqual(st.human_size(2048), "2.0K")
        self.assertEqual(st.human_size(1536 * 1024 * 1024), "1.5G")

    def test_ages_pick_a_useful_unit(self):
        self.assertEqual(st.human_age(30), "30 s")
        self.assertEqual(st.human_age(600), "10 min")
        self.assertEqual(st.human_age(7200), "2.0 h")
        self.assertEqual(st.human_age(3 * 86400), "3 d")


class ImportSafetyTest(unittest.TestCase):
    def test_a_missing_sibling_yields_none_rather_than_raising(self):
        self.assertIsNone(st._load_module("/does/not/exist.py", "nope"))

    def test_a_sibling_that_raises_on_import_yields_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.py")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write("raise RuntimeError('boom')\n")
            self.assertIsNone(st._load_module(broken, "broken"))

    def test_the_module_imports_no_ui_library(self):
        """Stage 3 puts Textual on top; the data layer must not need it."""
        with open(os.path.join(SCRIPTS, "ownerp_state.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("import textual", "import curses", "from textual"):
            self.assertNotIn(forbidden, source)

    def test_the_module_never_writes(self):
        """A status tool that can write is a status tool that can break things."""
        with open(os.path.join(SCRIPTS, "ownerp_state.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("os.replace(", "shutil.copy", "os.remove(",
                          "os.rmdir(", "os.chmod("):
            self.assertNotIn(forbidden, source)


class CronCollectionTest(StateFixture):
    def test_a_missing_cron_file_costs_only_its_section(self):
        result = st.collect_maintenance(
            cron_path=os.path.join(self.home, "no-such-cron"))
        self.assertFalse(result.known)
        self.assertEqual(result.jobs, [])

    def test_the_real_cron_template_parses(self):
        """The shipped template is what a server actually gets."""
        template = os.path.join(SCRIPTS, "myodoo-maintenance.cron")
        result = st.collect_maintenance(cron_path=template)
        self.assertTrue(result.known, result.error)
        self.assertGreater(len(result.jobs), 0)


if __name__ == "__main__":
    unittest.main()
