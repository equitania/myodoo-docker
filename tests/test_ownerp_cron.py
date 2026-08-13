"""
Tests for ownerp_cron.py — the maintenance-cron overview and editor.

The value of this module is entirely in its write path: cron accepts a
malformed line without a word and then simply never runs the job, so a bad
write is silent until the day a backup is needed. These tests pin the two
promises that make writing safe — only the named job changes, and an invalid
schedule never reaches the file.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_cron -v
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ownerp_cron as oc  # noqa: E402

REPO_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
TEMPLATE = os.path.join(REPO_SCRIPTS, "myodoo-maintenance.cron")


class CronFixture(unittest.TestCase):
    """Operates on a copy of the real shipped cron file, not a toy fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "myodoo-maintenance")
        shutil.copy2(TEMPLATE, self.path)
        with open(TEMPLATE, "r", encoding="utf-8") as handle:
            self.original = handle.read()

    def load(self):
        return oc.load(self.path)

    def text(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()


class ParsingTest(CronFixture):
    def test_every_shipped_job_is_found(self):
        cron = self.load()
        self.assertEqual(len(cron.jobs), 8)

    def test_duplicate_scripts_get_numbered_ids(self):
        """The backup runs twice a day from two lines; the name alone is ambiguous."""
        ids = [job.job_id for job in self.load().jobs]
        self.assertIn("container2backup.py:1", ids)
        self.assertIn("container2backup.py:2", ids)

    def test_interpreter_is_not_the_job_name(self):
        """`/usr/bin/python3 /root/odoo_build_cache.py gc` is the build-cache job."""
        ids = [job.job_id for job in self.load().jobs]
        self.assertIn("odoo_build_cache.py", ids)
        self.assertNotIn("python3", ids)

    def test_comments_and_env_lines_are_not_jobs(self):
        cron = self.load()
        for job in cron.jobs:
            self.assertNotIn("MAILTO", job.command)
            self.assertFalse(job.command.startswith("#"))

    def test_log_path_is_read_from_the_redirect(self):
        job = self.load().job("cleanup-weblogs.py")
        self.assertEqual(job.log_path, "/var/log/cleanup-weblogs.log")

    def test_job_without_redirect_has_no_log(self):
        """server-readiness.py mails on drift instead — a design choice, not a defect."""
        job = self.load().job("server-readiness.py")
        self.assertIsNone(job.log_path)
        self.assertEqual(oc.describe(job), "no log")

    def test_ambiguous_lookup_is_refused_with_the_alternatives(self):
        with self.assertRaises(oc.CronError) as ctx:
            self.load().job("container2backup.py")
        self.assertIn("container2backup.py:1", str(ctx.exception))

    def test_unknown_job_lists_what_exists(self):
        with self.assertRaises(oc.CronError) as ctx:
            self.load().job("nope.py")
        self.assertIn("ssl-renew.sh", str(ctx.exception))


class HumaniseTest(unittest.TestCase):
    def test_daily(self):
        self.assertEqual(oc.humanise("0 2 * * *"), "daily 02:00")

    def test_weekday(self):
        self.assertEqual(oc.humanise("0 6 * * 1"), "Mondays 06:00")

    def test_sunday_is_both_0_and_7(self):
        self.assertEqual(oc.humanise("30 3 * * 0"), "Sundays 03:30")
        self.assertEqual(oc.humanise("30 3 * * 7"), "Sundays 03:30")

    def test_unrecognised_shape_is_shown_raw(self):
        """A wrong-but-friendly 'daily' would be worse than no translation."""
        self.assertEqual(oc.humanise("*/15 * * * *"), "*/15 * * * *")
        self.assertEqual(oc.humanise("0 2 1 * *"), "0 2 1 * *")


class ValidateScheduleTest(unittest.TestCase):
    def test_accepts_the_shapes_the_file_uses(self):
        for schedule in ("0 2 * * *", "30 4 * * *", "0 6 * * 1", "*/15 * * * *",
                         "0 0,12 * * *", "0 9-17 * * 1-5", "@daily"):
            self.assertIsNone(oc.validate_schedule(schedule), schedule)

    def test_rejects_a_wrong_field_count(self):
        self.assertIn("5 fields", oc.validate_schedule("0 2 * *"))

    def test_rejects_an_hour_cron_would_silently_never_run(self):
        self.assertIn("outside 0-23", oc.validate_schedule("0 25 * * *"))

    def test_rejects_a_minute_out_of_range(self):
        self.assertIn("outside 0-59", oc.validate_schedule("99 2 * * *"))

    def test_rejects_a_backwards_range(self):
        self.assertIn("backwards", oc.validate_schedule("0 17-9 * * *"))

    def test_rejects_a_zero_step(self):
        self.assertIn("positive", oc.validate_schedule("*/0 * * * *"))

    def test_rejects_a_non_numeric_field(self):
        self.assertIn("not a number", oc.validate_schedule("0 two * * *"))

    def test_rejects_an_unknown_shortcut(self):
        self.assertIn("unknown cron shortcut", oc.validate_schedule("@fortnightly"))


class WriteTest(CronFixture):
    def test_rescheduling_changes_exactly_one_job_line(self):
        oc.set_schedule(self.load(), "cleanup-weblogs.py", "15 3 * * *")
        before = self.original.splitlines()
        after = self.text().splitlines()
        changed = [l for l in after if l not in before]
        # The job line plus the customisation marker, and nothing else.
        self.assertEqual(len(changed), 2)
        self.assertTrue(any("15 3 * * * root" in l for l in changed))
        self.assertTrue(any(l.startswith(oc.EDIT_MARKER) for l in changed))

    def test_untouched_lines_keep_their_alignment(self):
        """The template aligns columns with double spaces; a rewrite must not eat them."""
        oc.set_schedule(self.load(), "cleanup-weblogs.py", "15 3 * * *")
        self.assertIn("0 2  * * * root", self.text())

    def test_a_backup_is_written_before_the_change(self):
        _, backup = oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        self.assertTrue(os.path.exists(backup))
        with open(backup, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.original)

    def test_an_invalid_schedule_never_reaches_the_file(self):
        with self.assertRaises(oc.CronError):
            oc.set_schedule(self.load(), "ssl-renew.sh", "0 25 * * *")
        self.assertEqual(self.text(), self.original)

    def test_disabling_keeps_the_line_behind_a_marker(self):
        oc.set_active(self.load(), "nightly-cleanup.sh", False)
        self.assertIn(oc.DISABLED_PREFIX + "30 4 * * * root", self.text())

    def test_a_disabled_job_is_still_parsed_and_reversible(self):
        oc.set_active(self.load(), "nightly-cleanup.sh", False)
        job = self.load().job("nightly-cleanup.sh")
        self.assertFalse(job.active)
        self.assertEqual(job.schedule, "30 4 * * *")

        oc.set_active(self.load(), "nightly-cleanup.sh", True)
        restored = self.load().job("nightly-cleanup.sh")
        self.assertTrue(restored.active)
        self.assertEqual(restored.schedule, "30 4 * * *")
        self.assertNotIn(oc.DISABLED_PREFIX, self.text())

    def test_the_marker_is_written_once_no_matter_how_many_edits(self):
        oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        oc.set_schedule(self.load(), "cleanup-weblogs.py", "15 3 * * *")
        oc.set_active(self.load(), "nightly-cleanup.sh", False)
        markers = [l for l in self.text().splitlines()
                   if l.startswith(oc.EDIT_MARKER)]
        self.assertEqual(len(markers), 1)

    def test_the_written_file_is_readable_by_cron(self):
        """cron ignores a cron.d file that is group- or world-writable."""
        oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_the_file_still_parses_to_the_same_jobs(self):
        before = {job.job_id for job in self.load().jobs}
        oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        self.assertEqual({job.job_id for job in self.load().jobs}, before)


class RegressionGuardTest(CronFixture):
    def test_a_changed_job_count_is_refused(self):
        before = self.load()
        after = self.load()
        after.jobs.pop()
        problem = oc._regression(before, after, before.jobs[0])
        self.assertIn("job count changed", problem)

    def test_an_unrelated_job_changing_is_refused(self):
        before = self.load()
        after = self.load()
        after.jobs[3].schedule = "0 5 * * *"
        problem = oc._regression(before, after, before.jobs[0])
        self.assertIn("unrelated job", problem)

    def test_the_intended_job_changing_is_allowed(self):
        before = self.load()
        after = self.load()
        after.jobs[3].schedule = "0 5 * * *"
        self.assertIsNone(oc._regression(before, after, before.jobs[3]))


class MissingFileTest(unittest.TestCase):
    def test_a_missing_cron_file_names_the_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(oc.CronError) as ctx:
                oc.load(os.path.join(tmp, "nope"))
        self.assertIn("setup-maintenance-cron.sh", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
