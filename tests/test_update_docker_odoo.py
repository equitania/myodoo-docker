"""
Tests for the run log of update_docker_odoo.py.

Standard library only, like the rest of the suite. PyYAML is imported at module
level by the script but only used by load_config/save_updated_config; none of
the functions under test touch it, so a placeholder module stands in when it is
absent (customer servers and CI have the real one).

Run from the repository root:

    python3 -m unittest tests.test_update_docker_odoo -v
"""

import os
import re
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import update_docker_odoo as udo  # noqa: E402

LOG_NAME_PATTERN = re.compile(r"^update_\d{8}_\d{6}\.log$")


def read(path):
    with open(path, encoding="utf8") as handle:
        return handle.read()


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        udo.RUN_LOG_FILES.clear()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_the_log_lands_in_the_build_folder(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertEqual(os.path.dirname(path), self.tmp)
        self.assertTrue(os.path.isfile(path))

    def test_the_name_carries_date_and_time(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertRegex(os.path.basename(path), LOG_NAME_PATTERN)

    def test_the_header_names_the_container_and_the_script_version(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.close_run_log()
        content = read(path)
        self.assertIn("ivy-odoo", content)
        self.assertIn(udo.SCRIPT_VERSION, content)

    def test_extra_header_lines_are_written(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo",
                                header_lines=["image: odoo/ivy:latest"])
        udo.close_run_log()
        self.assertIn("image: odoo/ivy:latest", read(path))

    def test_written_lines_reach_the_file(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("build image odoo/ivy ... ok (23s)")
        udo.close_run_log()
        self.assertIn("build image odoo/ivy ... ok (23s)", read(path))

    def test_lines_are_flushed_before_the_log_is_closed(self):
        """A run killed mid-build must still leave its lines behind."""
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("stop ivy-odoo")
        self.assertIn("stop ivy-odoo", read(path))

    def test_carriage_returns_never_reach_the_file(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("\r  spinner residue\r")
        udo.close_run_log()
        self.assertNotIn("\r", read(path))

    def test_writing_without_an_open_log_is_ignored(self):
        udo.close_run_log()
        udo.run_log_write("nothing should happen here")  # must not raise

    def test_the_path_is_collected_for_the_closing_block(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertIn(path, udo.RUN_LOG_FILES)

    def test_a_second_container_gets_its_own_file(self):
        first = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.close_run_log()
        second_dir = tempfile.mkdtemp()
        second = udo.open_run_log(second_dir, "equitania-odoo")
        udo.close_run_log()
        self.assertNotEqual(first, second)
        self.assertEqual(udo.RUN_LOG_FILES, [first, second])

    def test_an_unwritable_folder_never_stops_the_run(self):
        """The log is a convenience. Losing it must not cost the update."""
        missing = os.path.join(self.tmp, "does", "not", "exist")
        self.assertIsNone(udo.open_run_log(missing, "ivy-odoo"))
        udo.run_log_write("still fine")  # must not raise


def age_log(directory, days, name_only=False):
    """Create a run log whose name puts it `days` days in the past."""
    stamp = time.strftime("%Y%m%d_%H%M%S",
                          time.localtime(time.time() - days * 86400))
    path = os.path.join(directory, f"update_{stamp}.log")
    if not name_only:
        with open(path, "w", encoding="utf8") as handle:
            handle.write("old run\n")
    return path


class PruneRunLogsTest(unittest.TestCase):
    """Deleting files needs a narrower target than a glob. Age comes from the
    name, which is also what proves the file is ours to delete."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_a_log_older_than_the_limit_is_removed(self):
        old = age_log(self.tmp, 120)
        self.assertEqual(udo.prune_run_logs(self.tmp, 90), 1)
        self.assertFalse(os.path.exists(old))

    def test_a_log_within_the_limit_survives(self):
        recent = age_log(self.tmp, 10)
        udo.prune_run_logs(self.tmp, 90)
        self.assertTrue(os.path.exists(recent))

    def test_the_boundary_sits_where_it_was_configured(self):
        """Not testable at exactly N days - the clock moves on between building
        the name and comparing it. A day either side is what matters."""
        just_inside = age_log(self.tmp, 89)
        just_outside = age_log(self.tmp, 91)
        self.assertEqual(udo.prune_run_logs(self.tmp, 90), 1)
        self.assertTrue(os.path.exists(just_inside))
        self.assertFalse(os.path.exists(just_outside))

    def test_only_this_script_s_own_log_names_are_touched(self):
        strangers = []
        for name in ("odoo.conf", "Dockerfile", "build.log", "update.log",
                     "update_2026.log", "update_20260101_120000.log.bak",
                     "release.file"):
            path = os.path.join(self.tmp, name)
            with open(path, "w", encoding="utf8") as handle:
                handle.write("not a run log\n")
            strangers.append(path)
        udo.prune_run_logs(self.tmp, 0.0001)
        for path in strangers:
            self.assertTrue(os.path.exists(path), f"deleted {path}")

    def test_a_directory_with_a_matching_name_is_left_alone(self):
        trap = os.path.join(self.tmp, "update_20200101_120000.log")
        os.makedirs(trap)
        udo.prune_run_logs(self.tmp, 1)
        self.assertTrue(os.path.isdir(trap))

    def test_subfolders_are_not_searched(self):
        nested = os.path.join(self.tmp, "filestore-backup")
        os.makedirs(nested)
        buried = age_log(nested, 999)
        udo.prune_run_logs(self.tmp, 1)
        self.assertTrue(os.path.exists(buried))

    def test_the_log_of_the_running_update_is_never_deleted(self):
        """Its name is minutes old, but a clock skew or a zero limit must not
        be able to delete the file currently being written."""
        current = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.prune_run_logs(self.tmp, 0.0001, keep=current)
        self.assertTrue(os.path.exists(current))

    def test_zero_days_disables_pruning(self):
        old = age_log(self.tmp, 3650)
        self.assertEqual(udo.prune_run_logs(self.tmp, 0), 0)
        self.assertTrue(os.path.exists(old))

    def test_no_setting_disables_pruning(self):
        old = age_log(self.tmp, 3650)
        self.assertEqual(udo.prune_run_logs(self.tmp, None), 0)
        self.assertTrue(os.path.exists(old))

    def test_a_missing_folder_never_stops_the_run(self):
        self.assertEqual(
            udo.prune_run_logs(os.path.join(self.tmp, "gone"), 90), 0)


class LogRetentionSettingTest(unittest.TestCase):
    def test_the_container_setting_wins(self):
        config = {"defaults": {"log_retention_days": 90}}
        container = {"log_retention_days": 7}
        self.assertEqual(udo.resolve_log_retention(config, container), 7)

    def test_the_defaults_block_applies_without_a_container_setting(self):
        config = {"defaults": {"log_retention_days": 30}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 30)

    def test_without_any_setting_the_built_in_default_applies(self):
        self.assertEqual(udo.resolve_log_retention({}, {}),
                         udo.DEFAULT_LOG_RETENTION_DAYS)

    def test_zero_is_kept_rather_than_treated_as_missing(self):
        """0 means 'never delete' - it must not fall through to the default."""
        config = {"defaults": {"log_retention_days": 0}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 0)

    def test_an_unusable_value_falls_back_to_the_default_instead_of_raising(self):
        config = {"defaults": {"log_retention_days": "ninety"}}
        self.assertEqual(udo.resolve_log_retention(config, {}),
                         udo.DEFAULT_LOG_RETENTION_DAYS)

    def test_a_negative_value_is_treated_as_disabled(self):
        config = {"defaults": {"log_retention_days": -5}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 0)


class DockerignoreTest(unittest.TestCase):
    """The build folder is the build context: every log file would otherwise be
    shipped to the daemon on every build."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_a_missing_dockerignore_is_created_with_the_log_pattern(self):
        udo.ensure_log_ignored(self.tmp)
        content = read(os.path.join(self.tmp, ".dockerignore"))
        self.assertIn("*.log", content.split())

    def test_an_existing_dockerignore_only_gains_the_pattern(self):
        path = os.path.join(self.tmp, ".dockerignore")
        with open(path, "w", encoding="utf8") as handle:
            handle.write("filestore-backup/\nrelease.file-*\n")
        udo.ensure_log_ignored(self.tmp)
        lines = read(path).split()
        self.assertIn("filestore-backup/", lines)
        self.assertIn("release.file-*", lines)
        self.assertIn("*.log", lines)

    def test_a_dockerignore_that_already_covers_logs_is_left_alone(self):
        path = os.path.join(self.tmp, ".dockerignore")
        original = "__pycache__/\n*.log\n*.tmp\n"
        with open(path, "w", encoding="utf8") as handle:
            handle.write(original)
        udo.ensure_log_ignored(self.tmp)
        self.assertEqual(read(path), original)

    def test_a_commented_out_pattern_does_not_count_as_covered(self):
        path = os.path.join(self.tmp, ".dockerignore")
        with open(path, "w", encoding="utf8") as handle:
            handle.write("# *.log\n")
        udo.ensure_log_ignored(self.tmp)
        self.assertIn("*.log", read(path).split())

    def test_an_unwritable_folder_never_stops_the_run(self):
        udo.ensure_log_ignored(os.path.join(self.tmp, "nope"))  # must not raise


class RunLogCaptureTest(unittest.TestCase):
    """Child output the quiet console drops must still be in the file - that is
    the entire point of the feature."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_filtered_info_lines_are_still_logged(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_command("echo plain-info-line", show_output=False,
                        filter_output=True)
        udo.close_run_log()
        self.assertIn("plain-info-line", read(path))

    def test_warnings_and_errors_are_logged_too(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_command("echo 'WARNING something is off' 1>&2",
                        show_output=False, filter_output=True)
        udo.close_run_log()
        self.assertIn("something is off", read(path))


if __name__ == "__main__":
    unittest.main()
