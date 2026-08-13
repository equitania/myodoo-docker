"""
Tests for ownerp_migrate.py — the one-way CSV to YAML conversion.

Two properties matter more than the mapping itself, and both are here:

  * nothing is destroyed. An existing YAML is never overwritten, a CSV is never
    deleted, and a conversion that does not validate is never installed.
  * a switched-off row stays switched off. Dropping it loses configuration;
    activating it silently starts backing up — or updating — something somebody
    deliberately turned off.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_migrate -v
"""

import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ownerp_migrate as om  # noqa: E402

try:
    import yaml
    HAVE_YAML = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_YAML = False

# The real shipped rows, from the CSV template as it existed before the switch.
BACKUP_CSV = """\
# Date 18.07.2021
#DATABASENAME,DBUSER,CONTAINERNAME-DB,MYODOO-CONTAINERNAME,STORETIME(days)
live_db,ownerp,live-db,live-myodoo,5
test_db,ownerp,test-db,test-myodoo,3
#alt_db,otheruser,alt-db,alt-myodoo,9
"""

UPDATE_CSV = """\
# [M]odules, [F]ull update or [N]eutralize DB,timeout(sec)
# Parameters: containername, databasename, port, longpollingport,
              path2Dockfile, docker_image_name, postgresql_username
# Date 19.09.2024
F,30,live-odoo,live_db,127.0.0.1:11000,127.0.0.1:12000,/root/docker-builds/live-odoo/,odoo/live,ownerp,secret123,live-db,"--network live-db-net -v /opt/odoo/live:/opt/odoo/data","16","Y"
#M,30,test-odoo,test_db,127.0.0.1:13000,127.0.0.1:14000,/root/docker-builds/test-odoo/,odoo/test,ownerp,secret123,test-db,"--network test-db-net","16","N"
"""

RSYNC_CSV = """\
rsync --delete -avzre "ssh" /opt/backups/ user@rsync.example.com:/users/user/bk/
#rsync -avz /root/ user@other:/backup/
"""


class MigrateFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def write(self, name, text):
        path = os.path.join(self.home, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(text))
        return path

    def read(self, name):
        with open(os.path.join(self.home, name), "r", encoding="utf-8") as handle:
            return handle.read()

    def result(self, results, name):
        return next(r for r in results if r.name == name)


class ReadingTest(MigrateFixture):
    def test_header_comments_are_not_mistaken_for_rows(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        rows = om.read_backup_csv(os.path.join(self.home, om.BACKUP_CSV))
        self.assertEqual([r.values["name"] for r in rows],
                         ["live_db", "test_db", "alt_db"])

    def test_a_commented_row_is_read_as_switched_off(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        rows = om.read_backup_csv(os.path.join(self.home, om.BACKUP_CSV))
        self.assertEqual([r.active for r in rows], [True, True, False])

    def test_the_update_header_block_is_skipped(self):
        """Its wrapped 'Parameters:' line would otherwise parse as CSV."""
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        rows = om.read_update_csv(os.path.join(self.home, om.UPDATE_CSV))
        self.assertEqual([r.values["container_name"] for r in rows],
                         ["live-odoo", "test-odoo"])

    def test_a_quoted_volume_with_commas_survives(self):
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        rows = om.read_update_csv(os.path.join(self.home, om.UPDATE_CSV))
        self.assertEqual(rows[0].values["volume"],
                         "--network live-db-net -v /opt/odoo/live:/opt/odoo/data")


@unittest.skipUnless(HAVE_YAML, "the conversion is only meaningful if it parses")
class ConversionTest(MigrateFixture):
    def test_backup_csv_becomes_valid_yaml(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        self.write(om.BACKUP_PATH_CSV, "/opt/backups\n")
        self.write(om.RSYNC_CSV, RSYNC_CSV)
        om.migrate(self.home)

        data = yaml.safe_load(self.read(om.BACKUP_YAML))
        self.assertEqual([d["name"] for d in data["databases"]],
                         ["live_db", "test_db"])
        self.assertEqual(data["defaults"]["backup_path"], "/opt/backups")
        self.assertEqual(data["defaults"]["db_user"], "ownerp")
        self.assertEqual(data["databases"][0]["retention_days"], 5)
        self.assertEqual(data["databases"][1]["retention_days"], 3)

    def test_a_shared_db_user_is_hoisted_and_not_repeated(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        om.migrate(self.home)
        data = yaml.safe_load(self.read(om.BACKUP_YAML))
        for entry in data["databases"]:
            self.assertNotIn("db_user", entry)

    def test_a_differing_db_user_stays_on_its_database(self):
        self.write(om.BACKUP_CSV,
                   "a_db,userone,a-db,a-odoo,5\nb_db,usertwo,b-db,b-odoo,5\n")
        om.migrate(self.home)
        data = yaml.safe_load(self.read(om.BACKUP_YAML))
        self.assertNotIn("db_user", data["defaults"])
        self.assertEqual({e["db_user"] for e in data["databases"]},
                         {"userone", "usertwo"})

    def test_a_switched_off_database_is_kept_as_a_comment(self):
        """No key exists for it in the schema, so it must not silently vanish."""
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        om.migrate(self.home)
        text = self.read(om.BACKUP_YAML)
        self.assertIn("#  - name: alt_db", text)
        self.assertNotIn("alt_db", str(yaml.safe_load(text)["databases"]))

    def test_rsync_commands_are_carried_over(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        self.write(om.RSYNC_CSV, RSYNC_CSV)
        om.migrate(self.home)
        data = yaml.safe_load(self.read(om.BACKUP_YAML))
        self.assertTrue(data["rsync"]["enabled"])
        self.assertEqual(len(data["rsync"]["commands"]), 1)
        self.assertIn("rsync.example.com", data["rsync"]["commands"][0])

    def test_update_csv_becomes_valid_yaml(self):
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        om.migrate(self.home)
        containers = yaml.safe_load(self.read(om.UPDATE_YAML))["containers"]
        self.assertEqual(len(containers), 2)
        live = containers[0]
        self.assertEqual(live["container_name"], "live-odoo")
        self.assertEqual(live["database_name"], "live_db")
        self.assertEqual(live["port"], "127.0.0.1:11000")
        self.assertEqual(live["db_password"], "secret123")
        self.assertEqual(live["odoo_version"], "16")
        self.assertEqual(live["translate"], "Y")
        self.assertEqual(live["delay_time"], 30)

    def test_a_commented_container_becomes_inactive_not_absent(self):
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        om.migrate(self.home)
        containers = yaml.safe_load(self.read(om.UPDATE_YAML))["containers"]
        self.assertTrue(containers[0]["active"])
        self.assertFalse(containers[1]["active"])
        self.assertEqual(containers[1]["container_name"], "test-odoo")

    def test_the_secure_password_default_is_added(self):
        """Not in the CSV format; argv passwords are visible via `ps aux`."""
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        om.migrate(self.home)
        containers = yaml.safe_load(self.read(om.UPDATE_YAML))["containers"]
        self.assertTrue(all(c["db_password_via_env"] for c in containers))


class SafetyTest(MigrateFixture):
    def test_an_existing_yaml_is_never_overwritten(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        self.write(om.BACKUP_YAML, "defaults:\n  retention_days: 99\n")
        results = om.migrate(self.home)

        self.assertEqual(self.result(results, "backup").status, "exists")
        self.assertIn("retention_days: 99", self.read(om.BACKUP_YAML))
        self.assertTrue(os.path.exists(
            os.path.join(self.home, om.BACKUP_YAML + ".from-csv")))

    def test_the_csv_stays_put_when_the_yaml_already_exists(self):
        """The operator still needs the source to compare against."""
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        self.write(om.BACKUP_YAML, "defaults: {}\n")
        om.migrate(self.home)
        self.assertTrue(os.path.exists(os.path.join(self.home, om.BACKUP_CSV)))

    def test_consumed_csvs_are_archived_not_deleted(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        self.write(om.RSYNC_CSV, RSYNC_CSV)
        results = om.migrate(self.home)

        self.assertFalse(os.path.exists(os.path.join(self.home, om.BACKUP_CSV)))
        archived = self.result(results, "backup").archived
        self.assertEqual(len(archived), 2)
        for path in archived:
            self.assertTrue(os.path.exists(path), path)

    def test_the_archive_is_not_world_readable(self):
        """docker2update.csv carries database passwords in clear text."""
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        results = om.migrate(self.home)
        directory = os.path.dirname(self.result(results, "update").archived[0])
        self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)

    def test_the_generated_config_is_not_world_readable(self):
        self.write(om.UPDATE_CSV, UPDATE_CSV)
        om.migrate(self.home)
        path = os.path.join(self.home, om.UPDATE_YAML)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_a_dry_run_writes_nothing(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        om.migrate(self.home, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.home, om.BACKUP_YAML)))
        self.assertTrue(os.path.exists(os.path.join(self.home, om.BACKUP_CSV)))

    def test_nothing_to_do_is_silent_and_clean(self):
        results = om.migrate(self.home)
        self.assertTrue(all(r.status == "none" for r in results))
        self.assertEqual(os.listdir(self.home), [])

    def test_running_twice_is_a_no_op_the_second_time(self):
        self.write(om.BACKUP_CSV, BACKUP_CSV)
        om.migrate(self.home)
        before = self.read(om.BACKUP_YAML)
        results = om.migrate(self.home)
        self.assertTrue(all(r.status == "none" for r in results))
        self.assertEqual(self.read(om.BACKUP_YAML), before)


class CleanupListTest(unittest.TestCase):
    def test_the_csvs_are_no_longer_marked_for_deletion(self):
        """cleanup_legacy_files() deletes what this list names, uncommented."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "cleanup_legacy.txt")
        with open(path, "r", encoding="utf-8") as handle:
            active = [l.strip() for l in handle
                      if l.strip() and not l.strip().startswith("#")]
        for name in (om.BACKUP_CSV, om.BACKUP_PATH_CSV, om.UPDATE_CSV,
                     om.RSYNC_CSV):
            self.assertNotIn(name, active)


if __name__ == "__main__":
    unittest.main()
