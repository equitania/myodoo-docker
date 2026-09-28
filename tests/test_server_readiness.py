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
import json
import os
import subprocess
import sys
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
        patcher2 = unittest.mock.patch.object(sr, "_container_count", return_value=2)
        patcher2.start()
        self.addCleanup(patcher2.stop)

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
                                        return_value="/usr/bin/docker"), \
             unittest.mock.patch.object(sr, "_container_count", return_value=2):
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
        # The alternative for a host that keeps the driver on purpose.
        self.assertIn("ownerp_mute.py docker_storage_driver", finding.fix)

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


GIB = 1024 ** 3


class OdooCapacityTest(unittest.TestCase):
    """A 4-CPU / 16 GB host with live and test on the shipped odoo.conf runs
    ten Odoo processes (3 workers + 2 cron threads each). Odoo's own sizing
    rule allows 2 x cores + 1 = 9, and the soft limits add up to 20 GiB, more
    than the whole machine has. Nothing said so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        patcher = unittest.mock.patch.object(sr.shutil, "which",
                                             return_value="/usr/bin/docker")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.containers = []

    def host(self, cpus, mem_gib):
        os.makedirs(os.path.join(self.tmp.name, "proc"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "proc", "cpuinfo"), "w") as handle:
            handle.write("".join(f"processor\t: {n}\nmodel name\t: x\n\n"
                                 for n in range(cpus)))
        with open(os.path.join(self.tmp.name, "proc", "meminfo"), "w") as handle:
            handle.write(f"MemTotal:       {mem_gib * 1024 * 1024} kB\n"
                         f"MemFree:        1024 kB\n")

    def instance(self, name, conf=None):
        source = f"/var/lib/docker/volumes/{name}-etc/_data"
        if conf is not None:
            folder = os.path.join(self.tmp.name, source.lstrip("/"))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "odoo.conf"), "w") as handle:
                handle.write(conf)
        self.containers.append({
            "Name": f"/{name}",
            "Mounts": [
                {"Source": source, "Destination": "/opt/odoo/etc"},
                {"Source": f"/opt/odoo/{name}", "Destination": "/opt/odoo/data"},
            ],
        })

    def fake_run(self, command, timeout=15):
        if command[:2] == ["docker", "ps"]:
            return 0, "\n".join(c["Name"].lstrip("/") for c in self.containers)
        if command[:2] == ["docker", "inspect"]:
            return 0, json.dumps(self.containers)
        return 1, "unexpected"

    def check(self):
        with unittest.mock.patch.object(sr, "_run", side_effect=self.fake_run):
            return sr.check_odoo_capacity(self.ctx)

    TEMPLATE = ("[options]\nworkers = 3\nmax_cron_threads = 2\n"
                "limit_memory_soft = 2147483648\n")

    def test_live_and_test_on_the_template_overload_4_cpus_16_gb(self):
        self.host(4, 16)
        self.instance("live-odoo", self.TEMPLATE)
        self.instance("test-odoo", self.TEMPLATE)
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("10 Odoo processes", finding.detail)
        self.assertIn("9", finding.detail)
        self.assertIn("20.0 GB", finding.detail)
        self.assertIn("live-odoo", finding.detail)
        self.assertIn("ownerp_mute.py odoo_capacity", finding.fix)

    def test_live_alone_on_the_template_fits(self):
        self.host(4, 16)
        self.instance("live-odoo", self.TEMPLATE)
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.OK, finding.detail)

    def test_memory_alone_can_overload(self):
        """Enough cores, too little RAM: 5 x 2 GiB = 10 GiB > 80 % of 8 GiB."""
        self.host(16, 8)
        self.instance("live-odoo", self.TEMPLATE)
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("memory", finding.detail)

    def test_cpu_alone_can_overload(self):
        self.host(2, 64)
        self.instance("live-odoo", "[options]\nworkers = 6\nmax_cron_threads = 1\n")
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("CPU", finding.detail)

    def test_odoo_defaults_apply_to_missing_keys(self):
        """No workers key means threaded mode: one process. Odoo's default
        soft limit is 2048 MiB."""
        self.host(1, 4)
        self.instance("live-odoo", "[options]\n")
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.OK, finding.detail)

    def test_an_unreadable_conf_is_named_not_guessed(self):
        self.host(4, 16)
        self.instance("live-odoo", self.TEMPLATE)
        self.instance("test-odoo", None)
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.OK)
        self.assertIn("test-odoo", finding.detail)

    def test_containers_without_an_odoo_etc_mount_are_ignored(self):
        self.host(4, 16)
        self.containers.append({"Name": "/live-db", "Mounts": [
            {"Source": "/opt/pg", "Destination": "/var/lib/postgresql/data"}]})
        finding = self.check()
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    def test_no_docker_is_skipped(self):
        with unittest.mock.patch.object(sr.shutil, "which", return_value=None):
            finding = sr.check_odoo_capacity(self.ctx)
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    def test_it_is_registered(self):
        self.assertIn(sr.check_odoo_capacity, sr.CHECKS)


class ConfigLoaderTest(unittest.TestCase):
    """Both configs go through one loader; the backup wrapper is what keeps
    its two callers unchanged."""

    def test_the_backup_wrapper_points_at_the_backup_file(self):
        with tempfile.TemporaryDirectory() as home:
            ctx = sr.HealthContext(root=home, home=home, repo=home)
            _config, error = sr._load_backup_config(ctx)
        self.assertIn(sr.BACKUP_CONFIG, error)


def _area(check_id, status="ok", findings=(), on_fail="FAIL", modules=("ufw",)):
    return {"check_id": check_id, "modules": list(modules), "on_fail": on_fail,
            "status": status, "findings": list(findings)}


GOOD_ENV = {"path": "/root/.config/myodoo-docker/.env", "present": True,
            "loaded": True, "ssh_port": 22, "allowed_ips": 2}


class HardeningChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)

    def audit(self, env=GOOD_ENV, areas=(), error=None):
        self.ctx._hardening_cache = ({"version": "1.9.0", "env": env,
                                      "areas": list(areas), "error": error}, None)

    def check(self, check_id):
        return next(c for c in sr.CHECKS if c.__name__ == f"check_{check_id}")(self.ctx)

    def test_all_checks_are_registered(self):
        names = {c.__name__ for c in sr.CHECKS}
        for check_id, _ in sr.HARDENING_AREAS:
            self.assertIn(f"check_{check_id}", names)
        self.assertIn("check_hardening_env", names)
        self.assertIn("check_root_login_locked", names)

    def test_readiness_and_hardening_agree_on_the_areas(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "scripts", "server_hardening.py")
        spec = importlib.util.spec_from_file_location("server_hardening", path)
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        self.assertEqual([a[0] for a in sh.AREAS], [a[0] for a in sr.HARDENING_AREAS])

    def test_a_failing_firewall_is_a_fail_with_the_command(self):
        self.audit(areas=[_area("hardening_firewall", "fail",
                                [{"module": "ufw", "level": "fail", "text": "UFW ist NICHT aktiv"},
                                 {"module": "ufw", "level": "fail", "text": "x"}])])
        finding = self.check("hardening_firewall")
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("UFW ist NICHT aktiv (+1 more)", finding.detail)
        self.assertIn("server_hardening.py --apply -m ufw", finding.fix)

    def test_a_warn_area_stays_warn_even_on_fail(self):
        self.audit(areas=[_area("hardening_kernel", "fail", [{"module": "sysctl",
                   "level": "fail", "text": "rp_filter"}], on_fail="WARN",
                   modules=("sysctl", "sysctl_persist", "kernel_modules"))])
        self.assertEqual(self.check("hardening_kernel").severity, sr.Severity.WARN)

    def test_ok_area_is_ok(self):
        self.audit(areas=[_area("hardening_ssh", "ok", modules=("ssh",))])
        self.assertEqual(self.check("hardening_ssh").severity, sr.Severity.OK)

    def test_missing_env_fails_and_areas_skip(self):
        self.audit(env={"path": "/root/.config/myodoo-docker/.env", "present": False,
                        "loaded": False, "ssh_port": None, "allowed_ips": 0},
                   error="ssh.port invalid: ''")
        env = self.check("hardening_env")
        self.assertEqual(env.severity, sr.Severity.FAIL)
        self.assertIn("ups", env.fix)
        self.assertEqual(self.check("hardening_firewall").severity, sr.Severity.SKIP)

    def test_env_without_admin_ips_fails(self):
        self.audit(env=dict(GOOD_ENV, allowed_ips=0))
        self.assertEqual(self.check("hardening_env").severity, sr.Severity.FAIL)

    def test_a_present_env_with_a_config_error_fails_with_the_real_message(self):
        # A bad ALLOWED_IP or an out-of-range SSH_PORT used to be invisible
        # here: env.present/loaded/ssh_port all looked fine and data["error"]
        # was never read, while every hardening_* area SKIPped on the same
        # error underneath - a report that read OK and mailed nothing.
        self.audit(env=dict(GOOD_ENV), error="Invalid IP address: 'nope'")
        finding = self.check("hardening_env")
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("Invalid IP address", finding.detail)
        self.assertIn("mcedit", finding.fix)

    def test_an_error_unrelated_to_the_env_skips_instead_of_no_env(self):
        # "root required" fires before load_env() runs - env is {} (present
        # unknown), and this must not be read as "no .env" (env.present is
        # not explicitly False here, it is simply not known).
        self.audit(env={}, error="root required")
        finding = self.check("hardening_env")
        self.assertEqual(finding.severity, sr.Severity.SKIP)
        self.assertIn("root required", finding.detail)

    def test_no_script_is_skip_not_alarm(self):
        finding = self.check("hardening_firewall")
        self.assertEqual(finding.severity, sr.Severity.SKIP)
        self.assertIn("server_hardening.py", finding.detail)

    def test_the_audit_runs_once_per_report(self):
        script = os.path.join(self.tmp.name, "server_hardening.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("import json\nprint(json.dumps({'env': {}, 'areas': [], 'error': None}))\n")
        with unittest.mock.patch.object(sr.subprocess, "run",
                                        wraps=subprocess.run) as spy:
            sr._hardening_audit(self.ctx)
            sr._hardening_audit(self.ctx)
        self.assertEqual(spy.call_count, 1)

    def test_timeout_and_garbage_are_skip(self):
        with unittest.mock.patch.object(sr.os.path, "isfile", return_value=True), \
             unittest.mock.patch.object(sr.subprocess, "run",
                                        side_effect=subprocess.TimeoutExpired("x", 1)):
            data, error = sr._hardening_audit(self.ctx)
        self.assertIsNone(data)
        self.assertIn("timed out", error)
        ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name, repo=self.tmp.name)
        with unittest.mock.patch.object(sr.os.path, "isfile", return_value=True), \
             unittest.mock.patch.object(sr.subprocess, "run", return_value=
                                        subprocess.CompletedProcess([], 1, "Traceback", "")):
            data, error = sr._hardening_audit(ctx)
        self.assertIsNone(data)

    def test_a_muted_area_is_muted(self):
        self.audit(areas=[_area("hardening_firewall", "fail",
                                [{"module": "ufw", "level": "fail", "text": "x"}])])
        mutes = os.path.join(self.tmp.name, sr.MUTES_RELATIVE)
        os.makedirs(os.path.dirname(mutes), exist_ok=True)
        with open(mutes, "w", encoding="utf-8") as handle:
            handle.write("hardening_firewall | 28.09.2026 | corporate firewall in front\n")
        with unittest.mock.patch.object(sr, "CHECKS",
                                        (next(c for c in sr.CHECKS
                                              if c.__name__ == "check_hardening_firewall"),)):
            findings = sr.run_checks(self.ctx)
        self.assertEqual(findings[0].severity, sr.Severity.MUTED)


class RootLoginLockedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        with open(os.path.join(self.tmp.name, "hardening_config.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write('ssh:\n  settings:\n    PermitRootLogin: "yes"\n')
        os.makedirs(os.path.join(self.tmp.name, "etc", "cloud"))
        with open(os.path.join(self.tmp.name, "etc", "cloud", "cloud.cfg"), "w",
                  encoding="utf-8") as handle:
            handle.write("disable_root: true\n")

    def run_check(self, passwd_output):
        with unittest.mock.patch.object(sr, "_run", return_value=(0, passwd_output)):
            return sr.check_root_login_locked(self.ctx)

    def test_locked_root_on_cloud_image_warns(self):
        finding = self.run_check("root L 2026-07-22 0 99999 7 -1")
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("disable_root", finding.detail)
        self.assertIn("passwd root", finding.fix)

    def test_root_with_password_is_ok(self):
        self.assertEqual(self.run_check("root P 2026-09-28 0 99999 7 -1").severity,
                         sr.Severity.OK)

    def test_config_not_expecting_root_is_skip(self):
        with open(os.path.join(self.tmp.name, "hardening_config.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write('ssh:\n  settings:\n    PermitRootLogin: "prohibit-password"\n')
        self.assertEqual(self.run_check("root L").severity, sr.Severity.SKIP)


class FreshHostHintTest(unittest.TestCase):
    """A host without any container has nothing --from-docker could rebuild."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        for patcher in (unittest.mock.patch.object(sr.shutil, "which",
                                                   return_value="/usr/bin/docker"),
                        unittest.mock.patch.object(sr, "_container_count", return_value=0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_update_config_points_at_wiz(self):
        finding = sr.check_update_config(self.ctx)
        self.assertIn("wizup", finding.fix)
        self.assertNotIn("--from-docker", finding.fix)

    def test_backup_config_points_at_wiz(self):
        finding = sr.check_backup_config(self.ctx)
        self.assertIn("wizup", finding.fix)
        self.assertNotIn("--from-docker", finding.fix)


if __name__ == "__main__":
    unittest.main()
