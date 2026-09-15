"""
Tests for the readiness checks themselves.

Written for check_update_config, which exists because its absence was the
defect: on 25.08.2026 a server was found with no docker2update.yaml at all
and a report that read 13 OK / 1 FAIL. The backup config had a check, the
update config had none, so half of a lost configuration was invisible.

Run from the repository root:

    python3 -m unittest tests.test_server_readiness -v
"""

import importlib.util
import os
import tempfile
import unittest
import unittest.mock

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server-readiness.py")
_spec = importlib.util.spec_from_file_location("server_readiness", _PATH)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_YAML = False

ENTRY = """\
containers:
  - container_name: live-odoo
    database_name: live_db
    port: 11000
    dockerfile_path: /root/docker-builds/live-odoo
    docker_image_name: live-odoo
    db_user: ownerp
    db_password: secret
    db_host: live-db
    odoo_version: 18.0
"""


class UpdateConfigTest(unittest.TestCase):
    """A host that cannot run `doup` must say so, exactly like one that
    cannot run `dobk`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        # The check asks whether docker exists before it asks anything else.
        patcher = unittest.mock.patch.object(sr.shutil, "which",
                                             return_value="/usr/bin/docker")
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, text):
        path = os.path.join(self.tmp.name, sr.UPDATE_CONFIG)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_it_is_registered(self):
        """A check that is not in CHECKS runs nowhere — which is the whole
        story of the finding this test exists for."""
        self.assertIn(sr.check_update_config, sr.CHECKS)

    def test_a_missing_file_fails_and_names_the_way_back(self):
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("not found", finding.detail)
        self.assertIn("--from-docker", finding.fix)

    def test_a_host_without_docker_is_skipped_not_failed(self):
        with unittest.mock.patch.object(sr.shutil, "which", return_value=None):
            finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_a_working_config_is_ok(self):
        self.write(ENTRY)
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)
        self.assertIn("1 of 1", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_a_parked_entry_is_counted_not_faulted(self):
        self.write(ENTRY + "    active: false\n" + ENTRY.split("\n", 1)[1]
                   .replace("live-odoo", "test-odoo")
                   .replace("live_db", "test_db")
                   .replace("live-db", "test-db")
                   .replace("11000", "11001"))
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)
        self.assertIn("1 of 2", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_every_entry_parked_warns(self):
        """doup then runs, updates nothing, and reports success."""
        self.write(ENTRY + "    active: false\n")
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("none active", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_no_containers_at_all_warns(self):
        self.write("containers: []\n")
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_unparseable_yaml_fails(self):
        self.write("containers: [\n  - broken: {{\n")
        finding = sr.check_update_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("invalid YAML", finding.detail)

    def test_it_can_be_muted_like_any_other_finding(self):
        self.assertNotIn("update_config", sr.UNMUTABLE)


class DuplicateCronEntriesTest(unittest.TestCase):
    """check_duplicate_cron_entries() reads every file in /etc/cron.d, but
    cron itself does not: run-parts naming (cron(8)) makes it skip any name
    outside [A-Za-z0-9_-]. Before this fix (15.09.2026) ownerp_cron.py's own
    backup — "myodoo-maintenance.bak_<timestamp>", written next to the file
    it edits — tripped the check while never actually running twice."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        self.cron_d = os.path.join(self.tmp.name, "etc", "cron.d")
        os.makedirs(self.cron_d)
        # The managed file itself must exist so a real duplicate is FAIL, not
        # WARN — the branch this test cares about.
        self.write("myodoo-maintenance", "0 2 * * * root /root/container2backup.py\n")
        # Avoid depending on the test runner's own crontab.
        patcher = unittest.mock.patch.object(sr, "_run", return_value=(1, ""))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, content):
        path = os.path.join(self.cron_d, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_a_stray_ownerp_cron_backup_is_not_reported(self):
        self.write("myodoo-maintenance.bak_20260915_112658",
                   "0 2 * * * root /root/container2backup.py\n")
        finding = sr.check_duplicate_cron_entries(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    def test_a_dot_free_foreign_file_is_still_reported(self):
        self.write("legacy-backup-cron",
                   "0 2 * * * root /root/container2backup.py\n")
        finding = sr.check_duplicate_cron_entries(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("legacy-backup-cron", finding.detail)


class ConfigLoaderTest(unittest.TestCase):
    """Both configs go through one loader; the backup wrapper is what keeps
    its two callers unchanged."""

    def test_the_backup_wrapper_points_at_the_backup_file(self):
        with tempfile.TemporaryDirectory() as home:
            ctx = sr.HealthContext(root=home, home=home, repo=home)
            _config, error = sr._load_backup_config(ctx)
        self.assertIn(sr.BACKUP_CONFIG, error)


if __name__ == "__main__":
    unittest.main()
