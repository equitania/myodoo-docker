"""
Tests for scripts/container2backup.py: the --validate delegation to
ownerp_validate.py, the backup_path fallback that prevents a mid-run
KeyError when a service block omits it, and check_paths()'s split between
hard path issues (abort a non-interactive run, unchanged) and FastReport
path issues (a per-database WARNING since 4.9.0 - that database's SQL dump
and filestore still run, only its FastReport part is skipped).

Standard library only, like the rest of the suite. container2backup.py
imports both PyYAML and python-dotenv at module level, but none of the
functions under test touch them, so placeholders stand in when they are
absent (customer servers and CI have the real ones).

Run from the repository root:

    python3 -m unittest tests.test_container2backup -v
"""

import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv)
import container2backup as c2b  # noqa: E402


class RunExternalValidationTest(unittest.TestCase):
    # NOTE: container2backup.py does a bare 'import os' and calls
    # os.path.isfile(...) / os.path.join(...) - there is no 'from os.path
    # import isfile' name to patch, so the patch target is c2b.os.path.isfile.

    def test_it_delegates_with_backup_flag_and_config_path(self):
        import subprocess
        recorded = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(c2b.os.path, "isfile", return_value=True), \
             mock.patch.object(c2b.subprocess, "run", side_effect=fake_run):
            code = c2b.run_external_validation("/etc/my.yaml")

        self.assertEqual(code, 0)
        self.assertIn("--backup", recorded["argv"])
        self.assertIn("/etc/my.yaml", recorded["argv"])
        self.assertTrue(recorded["argv"][1].endswith("ownerp_validate.py"))

    def test_it_passes_the_validators_exit_code_through(self):
        import subprocess
        with mock.patch.object(c2b.os.path, "isfile", return_value=True), \
             mock.patch.object(c2b.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            code = c2b.run_external_validation("/etc/my.yaml")
        self.assertEqual(code, 1)

    def test_a_missing_validator_exits_2_not_0(self):
        # container2backup.py has no older --validate behaviour to fall back
        # to, so silence must never look like a clean configuration - unlike
        # update_docker_odoo.py's (handled=False, 0), a missing validator here
        # is reported as "cannot check" via exit code 2.
        with mock.patch.object(c2b.os.path, "isfile", return_value=False):
            code = c2b.run_external_validation("/etc/my.yaml")
        self.assertEqual(code, 2)

    def test_the_validator_is_looked_for_beside_this_script(self):
        self.assertEqual(
            c2b.validator_path(),
            os.path.join(os.path.dirname(os.path.abspath(c2b.__file__)),
                         "ownerp_validate.py"))


class BackupAdditionalServiceTest(unittest.TestCase):
    def setUp(self):
        # backup_additional_service() calls compress_directory(), which does
        # real archive work - patch it out so these tests only exercise the
        # backup_path fallback / path-building logic.
        self.compress_patch = mock.patch.object(
            c2b, "compress_directory", return_value="/tmp/fake-archive.7z")
        self.compress_patch.start()
        self.addCleanup(self.compress_patch.stop)
        # backup_additional_service() reads the module-global 'config' (only
        # ever populated when the script runs as __main__) purely to pass it
        # through to the (here mocked) compress_directory - give it a value
        # so evaluating that argument does not NameError.
        self.config_patch = mock.patch.object(c2b, "config", {}, create=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.exists_patch = mock.patch.object(c2b.os.path, "exists", return_value=True)
        self.exists_patch.start()
        self.addCleanup(self.exists_patch.stop)
        self.makedirs_patch = mock.patch.object(c2b.os, "makedirs")
        self.makedirs_patch.start()
        self.addCleanup(self.makedirs_patch.stop)
        # The reserve check and the size walk read the real disk; the tests
        # here only care about path building, so stub both.
        for name, value in (("check_free_reserve", (True, "ok")),
                            ("estimate_service_bytes", 0)):
            patch = mock.patch.object(c2b, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_falls_back_to_the_service_name_when_backup_path_is_absent(self):
        service_config = {"source_path": "/etc/nginx"}
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        self.assertEqual(
            c2b.compress_directory.call_args[0][1],
            "/opt/backups/nginx/nginx_2026-08-11_00-00-00")

    def test_prefers_an_explicit_backup_path_when_present(self):
        service_config = {
            "source_path": "/etc/nginx",
            "backup_path": "custom-subdir",
        }
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        self.assertEqual(
            c2b.compress_directory.call_args[0][1],
            "/opt/backups/custom-subdir/custom-subdir_2026-08-11_00-00-00")

    def test_a_missing_source_path_is_skipped_not_a_keyerror(self):
        # check_paths() warns about this before the run and aborts under cron
        # or on the interactive default, but an operator answering 'y' to
        # "continue anyway?" used to reach a bare service_config['source_path']
        # here and get an unhandled KeyError instead of the clean skip the
        # earlier warning implied.
        service_config = {"backup_path": "nginx"}
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        c2b.compress_directory.assert_not_called()


class CheckPathsTest(unittest.TestCase):
    """check_paths() must keep service path problems as hard `issues` (the
    caller aborts a non-interactive run over these, unchanged) while a
    database's fast_report problems go into the separate, non-aborting
    `fastreport_warnings` list."""

    def test_a_missing_service_source_path_is_a_hard_issue(self):
        config = {
            "services": {"nginx": {"enabled": True, "source_path": "/does/not/exist-xyz"}},
            "databases": [],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(len(issues), 1)
        self.assertIn("nginx", issues[0])
        self.assertEqual(fastreport_warnings, [])

    def test_a_missing_fastreport_path_is_a_warning_not_an_issue(self):
        config = {
            "services": {},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": True, "path": "/does/not/exist-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 1)
        self.assertIn("live_db", fastreport_warnings[0])

    def test_fastreport_enabled_without_a_path_is_also_a_warning(self):
        config = {
            "services": {},
            "databases": [{"name": "live_db", "fast_report": {"enabled": True}}],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 1)
        self.assertIn("No fast-report path configured", fastreport_warnings[0])

    def test_a_disabled_fastreport_is_not_reported_at_all(self):
        config = {
            "services": {},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": False, "path": "/does/not/exist-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual((issues, fastreport_warnings), ([], []))

    def test_a_hard_issue_and_a_fastreport_warning_are_kept_apart(self):
        config = {
            "services": {"nginx": {"enabled": True, "source_path": "/does/not/exist-xyz"}},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": True, "path": "/also/missing-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(fastreport_warnings), 1)

    def test_two_databases_each_report_their_own_fastreport_problem(self):
        config = {
            "services": {},
            "databases": [
                {"name": "live_db", "fast_report": {"enabled": True, "path": "/missing-a"}},
                {"name": "test_db", "fast_report": {"enabled": True, "path": "/missing-b"}},
            ],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 2)
        joined = " ".join(fastreport_warnings)
        self.assertIn("live_db", joined)
        self.assertIn("test_db", joined)


class BackupFastReportTest(unittest.TestCase):
    """backup_fast_report() is what actually runs (or skips) a database's
    FastReport part; check_paths() only reports the problem up front."""

    def setUp(self):
        self.compress_patch = mock.patch.object(
            c2b, "compress_directory", return_value="/tmp/fake-fastreport.7z")
        self.compress_patch.start()
        self.addCleanup(self.compress_patch.stop)
        self.config_patch = mock.patch.object(c2b, "config", {}, create=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def test_a_missing_path_is_skipped_with_a_warning_naming_the_database(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True, "path": "/does/not/exist-xyz"},
                "/opt/backups", "2026-09-15_00-00-00")
        self.assertFalse(result)
        c2b.compress_directory.assert_not_called()
        output = buf.getvalue()
        self.assertIn("live_db", output)
        self.assertIn("skipped", output)

    def test_no_path_at_all_is_skipped_with_a_warning_naming_the_database(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True}, "/opt/backups", "2026-09-15_00-00-00")
        self.assertFalse(result)
        c2b.compress_directory.assert_not_called()
        self.assertIn("skipped", buf.getvalue())

    def test_an_existing_path_still_runs_the_fastreport_backup(self):
        with tempfile.TemporaryDirectory() as report_dir:
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True, "path": report_dir},
                "/opt/backups", "2026-09-15_00-00-00")
        self.assertTrue(result)
        c2b.compress_directory.assert_called_once()


GIB = 1024 ** 3


class DatabaseDataSizeTest(unittest.TestCase):
    """The pre-flight sizes the dump from table data only: indexes never end
    up in a pg_dump, and on an index-heavy Odoo database they can be 80% of
    pg_database_size - which refused backups that fit comfortably."""

    def test_the_probe_sums_table_size_and_not_database_size(self):
        done = mock.Mock(returncode=0, stdout=b"19327352832\n")
        with mock.patch.object(c2b.subprocess, "run", return_value=done) as run:
            size = c2b.get_database_data_size_bytes("live-db", "ownerp", "live_db")
        self.assertEqual(size, 19327352832)
        sql = run.call_args[0][0][-1]
        self.assertIn("pg_table_size", sql)
        self.assertNotIn("pg_database_size", sql)
        self.assertNotIn("live_db", sql)

    def test_a_failed_probe_returns_none(self):
        done = mock.Mock(returncode=2, stdout=b"")
        with mock.patch.object(c2b.subprocess, "run", return_value=done):
            self.assertIsNone(
                c2b.get_database_data_size_bytes("live-db", "ownerp", "live_db"))


class DiskPreflightTest(unittest.TestCase):
    """Numbers from a real refusal: 18 GiB table data (72 GiB indexes on
    top), 52.6 GiB filestore, 99.1 GiB free, temp and target on one mount."""

    def preflight(self, data_size, filestore_size, free, streaming=True):
        with mock.patch.object(c2b, "_free_bytes", return_value=int(free)), \
                mock.patch("sys.stdout", io.StringIO()):
            return c2b.disk_preflight(tempfile.gettempdir(), tempfile.gettempdir(),
                                      int(data_size), int(filestore_size), streaming)

    def test_streaming_passes_when_dump_and_archive_fit(self):
        ok, _ = self.preflight(18 * GIB, 52.6 * GIB, 99.1 * GIB)
        self.assertTrue(ok)

    def test_streaming_still_refuses_when_they_do_not(self):
        ok, msg = self.preflight(18 * GIB, 52.6 * GIB, 60 * GIB)
        self.assertFalse(ok)
        self.assertIn("SQL dump", msg)


class PreflightHintTest(unittest.TestCase):

    def test_streaming_is_not_recommended_when_it_already_runs(self):
        self.assertNotIn("stream: true", c2b.preflight_hint(streaming=True))

    def test_staging_still_recommends_streaming(self):
        self.assertIn("stream: true", c2b.preflight_hint(streaming=False))


class StaleTempDirsTest(unittest.TestCase):
    """A run killed mid-backup leaves its <db>_<timestamp> staging directory
    behind; nothing removed or reported it, so 41 GiB sat unnoticed for a year."""

    def test_leftovers_of_the_same_database_are_reported_but_kept(self):
        with tempfile.TemporaryDirectory() as base:
            for name in ("live_db_20250820_180002", "live_db_20260917_115437",
                         "other_db_20250101_000000", "live_db_notes"):
                os.makedirs(os.path.join(base, name))
            current = os.path.join(base, "live_db_20260917_115437")
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                stale = c2b.warn_stale_temp_dirs(base, "live_db", current)
            self.assertEqual([os.path.basename(p) for p in stale],
                             ["live_db_20250820_180002"])
            self.assertTrue(os.path.isdir(stale[0]))
            self.assertIn("live_db_20250820_180002", buf.getvalue())

    def test_a_clean_temp_path_prints_nothing(self):
        with tempfile.TemporaryDirectory() as base:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                self.assertEqual(c2b.warn_stale_temp_dirs(base, "live_db", None), [])
            self.assertEqual(buf.getvalue(), "")


class RetentionCoversEveryFormatTest(unittest.TestCase):
    """Until 4.9.2 retention skipped .sql.zst, .sql.gz and .7z.gpg - SQL-only
    and encrypted backups were never deleted (found 12.10.2026)."""

    ENDINGS = (".sql.zst", ".sql.gz", ".7z.gpg", ".tar.zst", ".7z")

    def make(self, folder, name, age_days):
        path = os.path.join(folder, name)
        with open(path, "w") as handle:
            handle.write("x")
        stamp = c2b.time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_old_archives_of_every_format_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            old = [self.make(folder, f"db_c_dockerbackup_20260901{e}", 30) for e in self.ENDINGS]
            new = [self.make(folder, f"db_c_dockerbackup_20261012{e}", 0) for e in self.ENDINGS]
            keep = self.make(folder, "notes.txt", 30)
            cutoff = c2b.time.time() - 86400
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                c2b.cleanup_backups_by_pattern(folder, cutoff, "db_c_dockerbackup_")
                c2b.cleanup_backups(folder, cutoff)
            self.assertEqual([p for p in old if os.path.exists(p)], [])
            self.assertTrue(all(os.path.exists(p) for p in new))
            self.assertTrue(os.path.exists(keep))


if __name__ == "__main__":
    unittest.main()


class ContainerPreCheckTest(unittest.TestCase):
    """12.10.2026: sql_container named a container the host did not have;
    every run printed "Backup completed!" and exited 0 while no database
    archive was ever written."""

    def test_missing_names_in_config_order(self):
        self.assertEqual(
            c2b.missing_containers(["it-db", "it-odoo"], {"it-odoo", "other"}),
            ["it-db"])

    def test_unknown_docker_state_reports_nothing(self):
        self.assertEqual(c2b.missing_containers(["it-db"], None), [])

    def test_docker_failure_is_none_not_empty(self):
        import subprocess
        failed = subprocess.CompletedProcess([], 1, b"", b"Cannot connect")
        with mock.patch.object(c2b.subprocess, "run", return_value=failed):
            self.assertIsNone(c2b.existing_container_names())

    def test_names_are_parsed(self):
        import subprocess
        ok = subprocess.CompletedProcess([], 0, b"live-db\nlive-odoo\n", b"")
        with mock.patch.object(c2b.subprocess, "run", return_value=ok):
            self.assertEqual(c2b.existing_container_names(), {"live-db", "live-odoo"})


class FailedDatabaseKeepsBackupsTest(unittest.TestCase):
    """A database without a new archive must keep its old ones and fail the run."""

    def setUp(self):
        with open(c2b.__file__, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_failed_backup_skips_retention_cleanup(self):
        failed = self.source.index('failed_databases.append(f"{db_name} (backup failed')
        cleanup = self.source.index("cleanup_backups_by_pattern(docker_backup_path")
        between = self.source[failed:cleanup]
        self.assertIn("continue", between)

    def test_run_exits_non_zero(self):
        tail = self.source[self.source.index("    if failed_databases or failed_services:"):]
        self.assertIn("sys.exit(1)", tail[:400])

    def test_failed_service_skips_retention_and_fails_the_run(self):
        failed = self.source.index("failed_services.append(")
        cleanup = self.source.index("cleanup_backups(service_backup_path")
        self.assertIn("continue", self.source[failed:cleanup])


class EncryptionEveryFormatTest(unittest.TestCase):
    """12.10.2026: format zstd + BACKUP_ENCRYPTION_ENABLED shipped plaintext
    archives offsite - encryption was dropped for every format but 7z. Since
    4.11.0 GPG encrypts the finished archive whatever its format."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "dump.sql"), "w") as handle:
            handle.write("select 1;\n")
        self.calls = []

        def fake_gpg(path, password):
            self.calls.append((path, password))
            os.replace(path, path + ".gpg")
            return path + ".gpg"

        patches = [
            mock.patch.object(c2b, "get_encryption_settings", return_value=(True, "pw")),
            mock.patch.object(c2b, "encrypt_file_with_gpg", side_effect=fake_gpg),
            mock.patch.object(c2b.shutil, "which", return_value="/usr/bin/gpg"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def compress(self, fmt, sql_only=False):
        config = {"defaults": {"compression": {"format": fmt, "level": 1}}}
        base = os.path.join(self.tmp.name, "out")
        with mock.patch("sys.stdout", new=io.StringIO()):
            return c2b.compress_directory(self.src, base, config, only_sql_dump=sql_only)

    def test_gzip_archive_is_encrypted(self):
        result = self.compress("gzip")
        self.assertTrue(result.endswith(".tar.gz.gpg"), result)
        self.assertEqual(len(self.calls), 1)

    def test_sql_only_gzip_is_encrypted(self):
        result = self.compress("gzip", sql_only=True)
        self.assertTrue(result.endswith(".sql.gz.gpg"), result)

    def test_every_encrypted_name_is_a_backup_suffix(self):
        for suffix in (".tar.zst.gpg", ".sql.zst.gpg", ".tar.gz.gpg", ".zip.gpg"):
            self.assertIn(suffix, c2b.BACKUP_SUFFIXES)

    def test_no_format_drops_encryption_silently(self):
        with open(c2b.__file__, encoding="utf-8") as handle:
            self.assertNotIn("Encryption will be ignored", handle.read())


class ExcludePatternTest(unittest.TestCase):
    """4.12.0: 'exclude:' for service backups (incident 09.11.2026: the
    hardlinked zips/ release cache was copied for real, 54 GB in 14 days)."""

    def test_docker_builds_defaults_to_the_zips_directories_only(self):
        self.assertEqual(c2b.service_excludes("docker_builds", {}), ["*/zips"])

    def test_top_level_release_zips_are_not_excluded_by_default(self):
        anchored = c2b.normalize_exclude_patterns(
            c2b.service_excludes("docker_builds", {}))
        self.assertFalse(c2b.is_excluded("build1/odoo_kernel.zip", anchored))
        self.assertTrue(c2b.is_excluded("build1/zips", anchored))
        self.assertTrue(c2b.is_excluded("build1/zips/odoo_kernel.zip", anchored))

    def test_an_empty_list_switches_the_default_off(self):
        self.assertEqual(c2b.service_excludes("docker_builds", {"exclude": []}), [])

    def test_an_explicit_list_replaces_the_default(self):
        self.assertEqual(
            c2b.service_excludes("docker_builds", {"exclude": ["*.bak"]}), ["*.bak"])

    def test_other_services_exclude_nothing_by_default(self):
        self.assertEqual(c2b.service_excludes("nginx", {}), [])
        self.assertEqual(c2b.service_excludes("nginx", {"exclude": None}), [])

    def test_a_malformed_value_is_ignored_with_a_warning(self):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            self.assertEqual(
                c2b.service_excludes("nginx", {"exclude": "zips"}), [])
        self.assertIn("must be a list of strings", out.getvalue())

    def test_a_pattern_without_slash_matches_at_any_depth(self):
        anchored = c2b.normalize_exclude_patterns(["*.bak", "cache/"])
        self.assertEqual(anchored, ["*.bak", "*/*.bak", "cache", "*/cache"])
        self.assertTrue(c2b.is_excluded("a/b/x.bak", anchored))
        self.assertTrue(c2b.is_excluded("x.bak", anchored))
        self.assertTrue(c2b.is_excluded("a/cache/f", anchored))
        self.assertFalse(c2b.is_excluded("a/b/x.txt", anchored))

    def test_leading_dot_slash_and_trailing_slash_are_normalised(self):
        self.assertEqual(c2b.normalize_exclude_patterns(["./b/zips/"]), ["b/zips"])


class ExcludeArgvTest(unittest.TestCase):
    """The generated argv for each compression format."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "docker-builds")
        os.makedirs(self.src)
        self.calls = []

        def fake_run(argv, **kwargs):
            self.calls.append(("run", list(argv), kwargs))
            out = [a for a in argv if str(a).startswith(self.tmp.name) and "out" in a]
            for path in out:
                with open(path, "wb") as handle:
                    handle.write(b"x")
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        class FakePopen:
            def __init__(inner, argv, **kwargs):
                self.calls.append(("popen", list(argv), kwargs))
                inner.stdout = io.BytesIO()
                inner.returncode = 0
                if "-o" in argv:
                    with open(argv[argv.index("-o") + 1], "wb") as handle:
                        handle.write(b"x")

            def communicate(inner):
                return b"", b""

        for patcher in (
            mock.patch.object(c2b.subprocess, "run", side_effect=fake_run),
            mock.patch.object(c2b.subprocess, "Popen", FakePopen),
            mock.patch.object(c2b, "check_compression_tools", return_value={
                "7zz": True, "zip": True, "gzip": True, "zstd": True}),
            mock.patch.object(c2b, "get_encryption_settings", return_value=(False, "")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def compress(self, fmt, exclude, system="Linux"):
        config = {"defaults": {"compression": {"format": fmt, "level": 3}}}
        base = os.path.join(self.tmp.name, "out")
        with mock.patch("sys.stdout", new=io.StringIO()), \
             mock.patch.object(c2b.platform, "system", return_value=system):
            return c2b.compress_directory(self.src, base, config, exclude=exclude)

    def test_7z_gets_one_switch_per_pattern_and_stores_symlinks(self):
        self.assertTrue(self.compress("7z", ["*/zips"]).endswith(".7z"))
        kind, argv, kwargs = self.calls[0]
        self.assertIn("-x!*/zips", argv)
        self.assertIn("-snl", argv)
        # switches precede the archive name; cwd is the source dir, input '.'
        self.assertLess(argv.index("-x!*/zips"), argv.index("."))
        self.assertEqual(argv[-1], ".")
        self.assertEqual(kwargs["cwd"], self.src)

    def test_zip_excludes_the_directory_and_its_content_after_the_input(self):
        self.assertTrue(self.compress("zip", ["*/zips"]).endswith(".zip"))
        argv = self.calls[0][1]
        tail = argv[argv.index("."):]
        self.assertEqual(tail, [".", "-y", "-x", "*/zips", "*/zips/*"])
        self.assertEqual(self.calls[0][2]["cwd"], self.src)

    def test_gzip_on_linux_prefixes_the_pattern_with_the_base_directory(self):
        self.compress("gzip", ["*/zips"], system="Linux")
        argv = self.calls[0][1]
        self.assertEqual(argv[:3], ["tar", "-czf", argv[2]])
        self.assertIn("--exclude=docker-builds/*/zips", argv)
        self.assertEqual(argv[-3:], ["-C", self.tmp.name, "docker-builds"])

    def test_gzip_on_macos_excludes_in_the_tar_stage(self):
        self.compress("gzip", ["*/zips"], system="Darwin")
        argv = self.calls[0][1]
        self.assertEqual(argv[:2], ["tar", "-cf"])
        self.assertIn("--exclude=docker-builds/*/zips", argv)

    def test_zstd_pipes_an_excluding_tar_into_zstd(self):
        self.compress("zstd", ["*/zips"])
        kind, argv, _ = self.calls[0]
        self.assertEqual(kind, "popen")
        self.assertEqual(argv[0], "tar")
        self.assertIn("--exclude=docker-builds/*/zips", argv)
        self.assertLess(argv.index("--exclude=docker-builds/*/zips"), argv.index("-C"))

    def test_without_excludes_the_argv_is_unchanged(self):
        self.compress("zip", [])
        self.assertEqual(self.calls[0][1][-1], ".")
        self.assertNotIn("-x", self.calls[0][1])
        self.assertNotIn("-y", self.calls[0][1])
        self.calls.clear()
        self.compress("7z", None)
        self.assertFalse([a for a in self.calls[0][1] if a.startswith("-x") or a == "-snl"])

    def test_sql_only_never_gets_excludes(self):
        config = {"defaults": {"compression": {"format": "zip", "level": 3}}}
        with open(os.path.join(self.src, "dump.sql"), "w") as handle:
            handle.write("select 1;")
        with mock.patch("sys.stdout", new=io.StringIO()):
            c2b.compress_directory(self.src, os.path.join(self.tmp.name, "out"),
                                   config, only_sql_dump=True, exclude=["*/zips"])
        self.assertNotIn("-x", self.calls[0][1])


@unittest.skipUnless(c2b.shutil.which("tar"), "tar not installed")
class ExcludeRealArchiveTest(unittest.TestCase):
    """The patterns must work with the real tools, not only in argv."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "docker-builds")
        os.makedirs(os.path.join(self.src, "b1", "zips"))
        os.makedirs(os.path.join(self.src, "b1", "addons"))
        os.makedirs(os.path.join(self.src, "b2", "zips"))
        for rel, text in (("b1/zips/kernel.zip", "k"), ("b1/addons/m.py", "m"),
                          ("b1/release.file", "r"), ("b1/hand-placed.zip", "h")):
            with open(os.path.join(self.src, rel), "w") as handle:
                handle.write(text)
        os.link(os.path.join(self.src, "b1/zips/kernel.zip"),
                os.path.join(self.src, "b2/zips/kernel.zip"))
        # A symlink to the excluded directory must not leak its content.
        os.symlink("b1/zips", os.path.join(self.src, "lnk"))

    def names(self, fmt):
        config = {"defaults": {"compression": {"format": fmt, "level": 1}}}
        base = os.path.join(self.tmp.name, "out_" + fmt)
        with mock.patch("sys.stdout", new=io.StringIO()), \
             mock.patch.object(c2b, "get_encryption_settings", return_value=(False, "")):
            archive = c2b.compress_directory(self.src, base, config, exclude=["*/zips"])
        self.assertTrue(archive and os.path.exists(archive), archive)
        return archive

    def assert_content(self, listing):
        self.assertIn("m.py", listing)
        self.assertIn("hand-placed.zip", listing)
        self.assertNotIn("kernel.zip", listing)

    def test_gzip(self):
        import subprocess
        if not c2b.shutil.which("gzip"):
            self.skipTest("gzip missing")
        archive = self.names("gzip")
        self.assert_content(subprocess.run(["tar", "-tzf", archive],
                                           capture_output=True, text=True).stdout)

    def test_zip(self):
        import subprocess
        if not (c2b.shutil.which("zip") and c2b.shutil.which("unzip")):
            self.skipTest("zip/unzip missing")
        archive = self.names("zip")
        self.assert_content(subprocess.run(["unzip", "-l", archive],
                                           capture_output=True, text=True).stdout)

    def test_7z(self):
        import subprocess
        if not c2b.shutil.which("7zz"):
            self.skipTest("7zz missing")
        archive = self.names("7z")
        self.assert_content(subprocess.run(["7zz", "l", archive],
                                           capture_output=True, text=True).stdout)

    def test_zstd(self):
        import subprocess
        if not c2b.shutil.which("zstd"):
            self.skipTest("zstd missing")
        archive = self.names("zstd")
        listing = subprocess.run(f"zstd -dc '{archive}' | tar -t", shell=True,
                                 capture_output=True, text=True).stdout
        self.assert_content(listing)


class EstimateServiceBytesTest(unittest.TestCase):
    def test_excluded_paths_and_repeated_inodes_are_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "b1", "zips"))
            with open(os.path.join(tmp, "b1", "zips", "big.zip"), "wb") as handle:
                handle.write(b"x" * 1000)
            with open(os.path.join(tmp, "b1", "keep.txt"), "wb") as handle:
                handle.write(b"y" * 10)
            os.link(os.path.join(tmp, "b1", "keep.txt"), os.path.join(tmp, "b1", "again.txt"))
            self.assertEqual(c2b.estimate_service_bytes(tmp, []), 1010)
            self.assertEqual(
                c2b.estimate_service_bytes(tmp, c2b.normalize_exclude_patterns(["*/zips"])), 10)


class FreeReserveTest(unittest.TestCase):
    GIB = 1024 ** 3

    def usage(self, total_gib, free_gib):
        return types.SimpleNamespace(total=total_gib * self.GIB,
                                     used=(total_gib - free_gib) * self.GIB,
                                     free=free_gib * self.GIB)

    def check(self, writes, usage, defaults, dev=lambda path: 1):
        with tempfile.TemporaryDirectory() as tmp:
            real = [(os.path.join(tmp, name), size * self.GIB) for name, size in writes]
            for path, _ in real:
                os.makedirs(path)
            with mock.patch.object(c2b.shutil, "disk_usage", return_value=usage), \
                 mock.patch.object(c2b.os, "stat",
                                   side_effect=lambda p: types.SimpleNamespace(st_dev=dev(p))):
                return c2b.check_free_reserve("live_db", real, defaults)

    def test_percent_reserve_wins_on_a_big_disk(self):
        # 1000 GiB disk, 10 % = 100 GiB; 150 free - 40 = 110 >= 100
        self.assertTrue(self.check([("a", 40)], self.usage(1000, 150), {})[0])
        # 150 - 60 = 90 < 100
        ok, msg = self.check([("a", 60)], self.usage(1000, 150), {})
        self.assertFalse(ok)

    def test_gb_reserve_wins_on_a_small_disk(self):
        # 20 GiB disk: 10 % = 2 GiB, min_free_gb 5 wins; 9 free - 5 = 4 < 5
        ok, msg = self.check([("a", 5)], self.usage(20, 9), {})
        self.assertFalse(ok)
        # 11 free - 5 = 6 >= 5
        self.assertTrue(self.check([("a", 5)], self.usage(20, 11), {})[0])

    def test_the_refusal_names_free_estimate_reserve_and_the_way_out(self):
        ok, msg = self.check([("a", 60)], self.usage(1000, 150), {})
        for needle in ("live_db", "free 150.0 GiB", "needs ~60.0 GiB",
                       "reserve to keep 100.0 GiB", "retention_days", "backup_path"):
            self.assertIn(needle, msg)

    def test_same_mount_writes_are_summed(self):
        usage = self.usage(1000, 150)
        # each alone leaves 120 >= 100, together 150 - 60 = 90 < 100
        self.assertTrue(self.check([("a", 30)], usage, {})[0])
        self.assertFalse(self.check([("a", 30), ("b", 30)], usage, {})[0])

    def test_different_mounts_are_checked_separately(self):
        usage = self.usage(1000, 150)

        def dev(path):
            return 2 if os.path.basename(path) == "b" else 1

        # a and b exist, so each is its own probe point with its own device.
        self.assertTrue(self.check([("a", 30), ("b", 30)], usage, {}, dev=dev)[0])

    def test_both_keys_zero_disable_the_check(self):
        ok, msg = self.check([("a", 900)], self.usage(1000, 10),
                             {"min_free_percent": 0, "min_free_gb": 0})
        self.assertTrue(ok)

    def test_one_key_zero_keeps_the_other_active(self):
        defaults = {"min_free_percent": 0, "min_free_gb": 5}
        self.assertFalse(self.check([("a", 6)], self.usage(1000, 10), defaults)[0])

    def test_invalid_values_fall_back_to_the_defaults(self):
        with mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(
                c2b.reserve_settings({"min_free_percent": "ten", "min_free_gb": -1}),
                (c2b.DEFAULT_MIN_FREE_PERCENT, c2b.DEFAULT_MIN_FREE_GB))

    def test_write_estimates_follow_the_preflight_factors(self):
        gib = self.GIB
        temp, target = c2b.backup_write_estimates(gib, 10 * gib, True, False)
        self.assertEqual(temp, int(gib * c2b.DUMP_SIZE_FACTOR))
        self.assertEqual(target, int(10 * gib * 0.9))
        temp, target = c2b.backup_write_estimates(gib, 10 * gib, False, True)
        self.assertEqual(target, int(gib * c2b.DUMP_SIZE_FACTOR * 0.3))
        self.assertEqual(c2b.backup_write_estimates(None, None, False, False), (0, 0))


class ServiceFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(self.src)
        patch = mock.patch.object(c2b, "config", {"defaults": {}}, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def run_service(self, name="nginx", cfg=None, **patches):
        cfg = dict(cfg or {"source_path": self.src, "backup_path": "svc"})
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            result = c2b.backup_additional_service(
                cfg, os.path.join(self.tmp.name, "bk"), "ts", name)
        return result, out.getvalue()

    def test_success_returns_true(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(True, "ok")), \
             mock.patch.object(c2b, "compress_directory", return_value="/x.7z"):
            self.assertTrue(self.run_service()[0])

    def test_a_failed_compression_returns_false(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(True, "ok")), \
             mock.patch.object(c2b, "compress_directory", return_value=None):
            self.assertFalse(self.run_service()[0])

    def test_a_refused_reserve_returns_false_and_writes_no_archive(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(False, "no room")), \
             mock.patch.object(c2b, "compress_directory") as compress:
            result, out = self.run_service()
        self.assertFalse(result)
        compress.assert_not_called()
        self.assertIn("ERROR: no room", out)

    def test_skips_and_disabled_services_are_not_failures(self):
        self.assertTrue(self.run_service(cfg={"enabled": False})[0])
        self.assertTrue(self.run_service(cfg={})[0])
        self.assertTrue(self.run_service(cfg={"source_path": "/nonexistent/x"})[0])

    def test_docker_builds_passes_the_default_exclude_and_announces_it(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(True, "ok")), \
             mock.patch.object(c2b, "compress_directory", return_value="/x.7z") as compress:
            _, out = self.run_service(name="docker_builds")
        self.assertEqual(compress.call_args.kwargs["exclude"], ["*/zips"])
        self.assertIn("Excluding from svc: */zips", out)

    def test_explicit_empty_exclude_passes_nothing(self):
        cfg = {"source_path": self.src, "backup_path": "svc", "exclude": []}
        with mock.patch.object(c2b, "check_free_reserve", return_value=(True, "ok")), \
             mock.patch.object(c2b, "compress_directory", return_value="/x.7z") as compress:
            _, out = self.run_service(name="docker_builds", cfg=cfg)
        self.assertEqual(compress.call_args.kwargs["exclude"], [])
        self.assertNotIn("Excluding", out)


class DatabaseBackupGuardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.temp_base = os.path.join(self.tmp.name, "temp")
        os.makedirs(self.temp_base)
        self.config = {"defaults": {"temp_path": self.temp_base}}
        for patcher in (
            mock.patch.object(c2b, "config", self.config, create=True),
            mock.patch.object(c2b, "get_database_data_size_bytes", return_value=10**9),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def backup(self, **kwargs):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            result = c2b.create_backup(
                "live_db", "u", "live-db", "live-odoo",
                os.path.join(self.tmp.name, "bk"), "ts", only_sql_dump=True, **kwargs)
        return result, out.getvalue()

    def test_a_refused_reserve_stops_before_pg_dump_and_cleans_the_temp_dir(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(False, "no room")), \
             mock.patch.object(c2b.subprocess, "run") as run:
            result, out = self.backup()
        self.assertFalse(result)
        run.assert_not_called()
        self.assertIn("ERROR: no room", out)
        self.assertEqual(os.listdir(self.temp_base), [])

    def test_the_reserve_check_gets_temp_and_target_estimates(self):
        with mock.patch.object(c2b, "check_free_reserve", return_value=(False, "x")) as check:
            self.backup()
        label, writes, _ = check.call_args[0]
        self.assertEqual(label, "live_db")
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0][0].startswith(self.temp_base))
        self.assertTrue(writes[1][0].endswith("/docker"))

    def test_two_runs_in_the_same_second_get_different_temp_dirs(self):
        made = []
        real = c2b.tempfile.mkdtemp

        def recording(*args, **kwargs):
            path = real(*args, **kwargs)
            made.append(path)
            return path

        fail = types.SimpleNamespace(returncode=1, stderr=b"")
        with mock.patch.object(c2b, "check_free_reserve", return_value=(True, "ok")), \
             mock.patch.object(c2b.tempfile, "mkdtemp", side_effect=recording), \
             mock.patch.object(c2b.subprocess, "run", return_value=fail), \
             mock.patch.object(c2b.datetime, "datetime", wraps=c2b.datetime.datetime) as dt:
            dt.now.return_value = c2b.datetime.datetime(2026, 11, 9, 2, 0, 0)
            self.backup()
            self.backup()
        self.assertEqual(len(made), 2)
        self.assertNotEqual(made[0], made[1])
        for path in made:
            self.assertRegex(os.path.basename(path), r"^live_db_20261109_020000_\w{8}$")
            self.assertEqual(os.path.dirname(path), self.temp_base)

    def test_stale_warning_recognises_old_and_new_temp_names(self):
        for name in ("live_db_20261109_020000", "live_db_20261109_020000_ab12cd34"):
            os.makedirs(os.path.join(self.temp_base, name))
        os.makedirs(os.path.join(self.temp_base, "other_db_20261109_020000_ab12cd34"))
        with mock.patch("sys.stdout", new=io.StringIO()):
            stale = c2b.warn_stale_temp_dirs(self.temp_base, "live_db", "")
        self.assertEqual(sorted(os.path.basename(p) for p in stale),
                         ["live_db_20261109_020000", "live_db_20261109_020000_ab12cd34"])


class RunLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = os.path.join(self.tmp.name, "c2b.lock")

    def test_the_first_run_holds_the_lock_and_stores_its_pid(self):
        handle, holder, path = c2b.acquire_run_lock(lock_path=self.lock)
        self.addCleanup(handle.close)
        self.assertIsNone(holder)
        self.assertEqual(path, self.lock)
        with open(self.lock) as reader:
            self.assertEqual(reader.read(), str(os.getpid()))

    def test_a_second_run_is_refused_and_writes_nothing(self):
        handle, _, _ = c2b.acquire_run_lock(lock_path=self.lock)
        self.addCleanup(handle.close)
        second, holder, path = c2b.acquire_run_lock(lock_path=self.lock)
        self.assertIsNone(second)
        self.assertEqual(holder, str(os.getpid()))
        with open(self.lock) as reader:
            self.assertEqual(reader.read(), str(os.getpid()))

    def test_the_lock_is_free_again_after_release(self):
        handle, _, _ = c2b.acquire_run_lock(lock_path=self.lock)
        handle.close()
        again, holder, _ = c2b.acquire_run_lock(lock_path=self.lock)
        self.addCleanup(again.close)
        self.assertIsNone(holder)

    def test_an_unwritable_primary_falls_back_to_the_temp_dir(self):
        primary = os.path.join(self.tmp.name, "missing-dir", "c2b.lock")
        handle, holder, path = c2b.acquire_run_lock(self.tmp.name, lock_path=primary)
        self.addCleanup(handle.close)
        self.assertEqual(path, os.path.join(self.tmp.name, "container2backup.lock"))

    def test_without_any_lock_file_the_run_continues_unlocked(self):
        primary = os.path.join(self.tmp.name, "missing-dir", "c2b.lock")
        self.assertEqual(c2b.acquire_run_lock(None, lock_path=primary), (None, None, None))


@unittest.skipUnless(c2b.yaml is not None and hasattr(c2b.yaml, "safe_load"),
                     "PyYAML not installed")
class RunRefusedWhileLockedTest(unittest.TestCase):
    """The whole script, started while another run holds the lock."""

    def test_second_run_exits_1_and_creates_nothing(self):
        import subprocess
        with tempfile.TemporaryDirectory() as home:
            temp = os.path.join(home, "temp")
            backups = os.path.join(home, "backups")
            os.makedirs(temp)
            with open(os.path.join(home, "container2backup.yaml"), "w") as handle:
                handle.write(f"defaults:\n  backup_path: {backups}\n  temp_path: {temp}\n"
                             "services: {}\ndatabases: []\n")
            # Take the lock exactly where the script will look for it.
            holder, none_yet, _ = c2b.acquire_run_lock(temp)
            self.assertIsNotNone(holder)
            self.addCleanup(holder.close)
            code = (
                "import sys, types, runpy\n"
                "m = types.ModuleType('dotenv'); m.load_dotenv = lambda *a, **k: None\n"
                "sys.modules['dotenv'] = m\n"
                f"sys.argv = ['container2backup.py']\n"
                f"runpy.run_path({c2b.__file__!r}, run_name='__main__')\n")
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                  text=True, env=dict(os.environ, HOME=home))
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("another container2backup run is active "
                          f"(PID {os.getpid()}) - this run stops.", proc.stdout)
            self.assertFalse(os.path.exists(backups))
            self.assertEqual(sorted(os.listdir(temp)), ["container2backup.lock"]
                             if not os.path.exists("/run/lock") else [])
