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
import time
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

    def test_the_fix_names_the_docron_alternative(self):
        """A host that runs no doup instances at all should not be steered
        towards reconstructing a config it will never use."""
        finding = sr.check_update_config(self.ctx)
        self.assertIn("docron --disable odoo_build_cache", finding.fix)

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


BACKUP_ENTRY = """\
databases:
  - name: live_db
    sql_container: live-db
    data_container: live-odoo
  - name: test_db
    sql_container: test-db
    data_container: test-odoo
"""


class BackupRecencyTest(unittest.TestCase):
    """check_backup_recency() reads the newest archive per configured
    database, the same way ownerp_state.find_archives does, instead of the
    backup log's mtime - an aborting run still touches the log (found
    15.09.2026 on a test server whose FastReport path had gone missing), so
    the log alone cannot tell a real backup from an aborted one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)

    def write_config(self, text):
        path = os.path.join(self.tmp.name, sr.BACKUP_CONFIG)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_log(self, text):
        path = self.ctx.p(sr.BACKUP_LOG)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def touch_archive(self, database, data_container, age_seconds,
                      suffix=".7z"):
        folder = self.ctx.p(os.path.join(sr.DEFAULT_BACKUP_PATH,
                                         sr.DOCKER_BACKUP_SUBDIR))
        os.makedirs(folder, exist_ok=True)
        name = f"{database}_{data_container}_dockerbackup_2026-09-15_00-00-00{suffix}"
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_fresh_archives_for_every_database_are_ok(self):
        self.write_config(BACKUP_ENTRY)
        self.touch_archive("live_db", "live-odoo", 3600)
        self.touch_archive("test_db", "test-odoo", 3600)
        finding = sr.check_backup_recency(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_a_stale_archive_warns_and_names_the_database(self):
        self.write_config(BACKUP_ENTRY)
        self.touch_archive("live_db", "live-odoo", 30 * 3600)
        self.touch_archive("test_db", "test-odoo", 3600)
        finding = sr.check_backup_recency(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("live_db", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_a_very_stale_archive_fails_and_names_the_database(self):
        self.write_config(BACKUP_ENTRY)
        self.touch_archive("live_db", "live-odoo", 60 * 3600)
        self.touch_archive("test_db", "test-odoo", 3600)
        finding = sr.check_backup_recency(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("live_db", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_no_archive_for_one_database_fails_and_names_it(self):
        self.write_config(BACKUP_ENTRY)
        self.touch_archive("live_db", "live-odoo", 3600)
        # test_db has no archive at all.
        finding = sr.check_backup_recency(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("test_db", finding.detail)
        self.assertIn("no archive found", finding.detail)

    def test_a_missing_yaml_falls_back_to_the_log(self):
        """backup_config() already FAILs on the missing YAML under its own
        title; this must not report the identical fact a second time."""
        self.write_log("some backup output\n")
        finding = sr.check_backup_recency(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)
        self.assertIn("last activity", finding.detail)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_the_log_shows_the_abort_line_is_mentioned(self):
        self.write_config(BACKUP_ENTRY)
        self.touch_archive("live_db", "live-odoo", 3600)
        self.touch_archive("test_db", "test-odoo", 3600)
        self.write_log(
            "Backup path: /opt/backups\n"
            "WARNING: The following issues were found:\n"
            "- Fast-report path /opt/fast-report/fr-live for database "
            "live_db does not exist\n"
            "Non-interactive run with path issues — aborting backup "
            "(run interactively to override).\n"
        )
        finding = sr.check_backup_recency(self.ctx)
        self.assertIn("aborted", finding.detail)

    def test_the_abort_line_is_mentioned_on_the_log_fallback_too(self):
        self.write_log(
            "Non-interactive run with path issues — aborting backup "
            "(run interactively to override).\n"
        )
        finding = sr.check_backup_recency(self.ctx)
        self.assertIn("aborted", finding.detail)

    def test_it_is_registered(self):
        self.assertIn(sr.check_backup_recency, sr.CHECKS)

    def test_it_can_still_be_derived_muted_when_the_cron_job_is_disabled(self):
        """The mute mechanism operates on check_id, independent of how the
        finding's own detail is computed - this must keep working."""
        cron_path = self.ctx.p(sr.CRON_DEST)
        os.makedirs(os.path.dirname(cron_path), exist_ok=True)
        with open(cron_path, "w", encoding="utf-8") as handle:
            handle.write("#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n")
        findings = sr.run_checks(self.ctx)
        finding = next(f for f in findings if f.check_id == "backup_recency")
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("cron job disabled", finding.note)


class BackupConfigTest(unittest.TestCase):
    """check_backup_config's counterpart test to UpdateConfigTest above."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)

    def test_the_fix_names_the_docron_alternative_with_docker(self):
        with unittest.mock.patch.object(sr.shutil, "which",
                                        return_value="/usr/bin/docker"):
            finding = sr.check_backup_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("docron --disable container2backup", finding.fix)

    def test_the_fix_names_the_docron_alternative_without_docker(self):
        with unittest.mock.patch.object(sr.shutil, "which", return_value=None):
            finding = sr.check_backup_config(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("docron --disable container2backup", finding.fix)


class DockerStorageDriverTest(unittest.TestCase):
    """The containerd store was cleared of causing broken images by the
    14.08.2026 A/B test - what remains is a measured speed cost, so a
    non-overlay2 driver is a WARN, never a FAIL, and the message must not
    blame moby#52431 any more."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        patcher = unittest.mock.patch.object(sr.shutil, "which",
                                             return_value="/usr/bin/docker")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_overlay2_is_ok(self):
        with unittest.mock.patch.object(sr, "_run", return_value=(0, "overlay2\n")):
            finding = sr.check_docker_storage_driver(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    def test_a_different_driver_warns_not_fails(self):
        with unittest.mock.patch.object(sr, "_run", return_value=(0, "overlayfs\n")):
            finding = sr.check_docker_storage_driver(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertNotIn("moby", finding.detail)
        self.assertNotIn("moby", finding.fix)

    def test_a_host_without_docker_is_skipped(self):
        with unittest.mock.patch.object(sr.shutil, "which", return_value=None):
            finding = sr.check_docker_storage_driver(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    def test_it_is_registered(self):
        self.assertIn(sr.check_docker_storage_driver, sr.CHECKS)


class AvOnAccessScannerTest(unittest.TestCase):
    """check_av_on_access_scanner() - a Sophos on-access policy that still
    watches /var/lib/docker is the established root cause of hollow Docker
    images on one customer server. See docs/specs/2026-08-02-server-readiness-
    check-design.md, addendum 15.09.2026."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        patcher = unittest.mock.patch.object(sr.shutil, "which",
                                             return_value="/usr/bin/docker")
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_policy(self, payload):
        path = self.ctx.p(sr.SOPHOS_ON_ACCESS_POLICY)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def install_sophos(self):
        os.makedirs(self.ctx.p(sr.SOPHOS_ROOT), exist_ok=True)

    def test_it_is_registered(self):
        self.assertIn(sr.check_av_on_access_scanner, sr.CHECKS)

    def test_no_sophos_at_all_is_skipped(self):
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.SKIP)
        self.assertIn("no Sophos", finding.detail)

    def test_sophos_present_but_no_docker_is_skipped(self):
        self.install_sophos()
        with unittest.mock.patch.object(sr.shutil, "which", return_value=None):
            finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.SKIP)
        self.assertIn("docker not installed", finding.detail)

    def test_an_unreadable_policy_warns(self):
        self.install_sophos()
        # Directory present, policy file absent -> unreadable.
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("/var/lib/docker/", finding.fix)

    def test_an_unparseable_policy_warns(self):
        self.install_sophos()
        self.write_policy("{not json")
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)

    def test_an_unrecognised_shape_warns(self):
        self.install_sophos()
        self.write_policy('{"something_else": true}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.WARN)

    def test_on_access_disabled_is_ok(self):
        self.install_sophos()
        self.write_policy('{"enabled": false, "exclusions": []}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)
        self.assertIn("off", finding.detail)

    def test_excluded_with_the_broad_path_is_ok(self):
        self.install_sophos()
        self.write_policy(
            '{"enabled": true, "onOpen": true, "onClose": true, '
            '"exclusions": ["/var/lib/docker/"]}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    def test_excluded_with_the_broad_path_without_trailing_slash_is_ok(self):
        self.install_sophos()
        self.write_policy(
            '{"enabled": true, "exclusions": ["/var/lib/docker"]}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    def test_excluded_with_all_three_narrow_paths_is_ok(self):
        self.install_sophos()
        self.write_policy(
            '{"enabled": true, "exclusions": ['
            '"/var/lib/docker/buildkit/", '
            '"/var/lib/docker/tmp/", '
            '"/var/lib/docker/overlay2/"]}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.OK)

    def test_only_two_of_the_three_narrow_paths_still_fails(self):
        self.install_sophos()
        self.write_policy(
            '{"enabled": true, "exclusions": ['
            '"/var/lib/docker/buildkit/", '
            '"/var/lib/docker/tmp/"]}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)

    def test_enabled_and_not_excluded_fails_with_the_exact_path_in_the_fix(self):
        self.install_sophos()
        self.write_policy('{"enabled": true, "exclusions": []}')
        finding = sr.check_av_on_access_scanner(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("/var/lib/docker/", finding.fix)
        self.assertIn("hollow images", finding.detail)


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
