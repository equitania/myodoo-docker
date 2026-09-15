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

import io
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


class SwitchByScriptTest(CronFixture):
    """A server without backups has neither backup line. One call, both lines."""

    def active(self, job_id):
        return self.load().job(job_id).active

    def test_script_name_switches_every_line_of_it(self):
        jobs, _backup = oc.set_active(self.load(), "container2backup.py", False)
        self.assertEqual([j.job_id for j in jobs],
                         ["container2backup.py:1", "container2backup.py:2"])
        self.assertFalse(self.active("container2backup.py:1"))
        self.assertFalse(self.active("container2backup.py:2"))

    def test_the_name_works_without_py(self):
        oc.set_active(self.load(), "container2backup", False)
        self.assertFalse(self.active("container2backup.py:1"))
        self.assertFalse(self.active("container2backup.py:2"))
        oc.set_active(self.load(), "odoo_build_cache", False)
        self.assertFalse(self.active("odoo_build_cache.py"))

    def test_an_exact_id_still_switches_one_line(self):
        """The console toggles a row by its id; that must stay one line."""
        oc.set_active(self.load(), "container2backup.py:2", False)
        self.assertTrue(self.active("container2backup.py:1"))
        self.assertFalse(self.active("container2backup.py:2"))

    def test_nothing_else_changes(self):
        oc.set_active(self.load(), "container2backup", False)
        before = oc.parse_text(self.original, path=self.path)
        after = self.load()
        for old, new in zip(before.jobs, after.jobs):
            if old.script == "container2backup.py":
                continue
            self.assertEqual((old.schedule, old.command, old.active),
                             (new.schedule, new.command, new.active))

    def test_enable_restores_every_job_as_it_was(self):
        """A rewritten line loses its column padding; the job itself must not
        change - schedule, command and state are what cron reads."""
        oc.set_active(self.load(), "container2backup", False)
        oc.set_active(self.load(), "container2backup", True)
        before = oc.parse_text(self.original, path=self.path)
        after = self.load()
        self.assertEqual(
            [(j.job_id, j.schedule, j.user, j.command, j.active) for j in before.jobs],
            [(j.job_id, j.schedule, j.user, j.command, j.active) for j in after.jobs])

    def test_cli_disables_both_lines_in_one_call(self):
        code = oc.main(["--path", self.path, "--disable", "container2backup"])
        self.assertEqual(code, 0)
        self.assertFalse(self.active("container2backup.py:1"))
        self.assertFalse(self.active("container2backup.py:2"))

    def test_unknown_name_is_refused_and_the_file_untouched(self):
        with self.assertRaises(oc.CronError):
            oc.set_active(self.load(), "container2back", False)
        self.assertEqual(self.text(), self.original)

    def test_set_schedule_stays_strict(self):
        """A schedule belongs to one line - a name that means two is refused."""
        with self.assertRaises(oc.CronError):
            oc.set_schedule(self.load(), "container2backup.py", "0 3 * * *")


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


class BackupLocationTest(unittest.TestCase):
    """_backup() must never write inside cron.d (fixed 15.09.2026): a copy
    named "myodoo-maintenance.bak_..." sits exactly where cron.d's own
    run-parts naming rule (cron(8): only [A-Za-z0-9_-]) hides it from cron,
    but server-readiness.py's check_duplicate_cron_entries() read every file
    in the directory and reported it as a competing schedule."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cron_d = os.path.join(self.tmp.name, "etc", "cron.d")
        os.makedirs(self.cron_d)
        self.path = os.path.join(self.cron_d, "myodoo-maintenance")
        shutil.copy2(TEMPLATE, self.path)

        self.backup_dir = os.path.join(self.tmp.name, "backups")
        old_backup_dir = oc.BACKUP_DIR
        oc.BACKUP_DIR = self.backup_dir
        self.addCleanup(setattr, oc, "BACKUP_DIR", old_backup_dir)

    def load(self):
        return oc.load(self.path)

    def test_backup_lands_in_backup_dir_for_a_cron_d_file(self):
        _job, backup = oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        self.assertEqual(os.path.dirname(backup), self.backup_dir)
        self.assertTrue(os.path.basename(backup).startswith(
            "myodoo-maintenance.bak_"))
        self.assertTrue(os.path.exists(backup))
        self.assertEqual(
            [n for n in os.listdir(self.cron_d) if ".bak_" in n], [])

    def test_backup_stays_next_to_the_file_outside_cron_d(self):
        outside = os.path.join(self.tmp.name, "myodoo-maintenance")
        shutil.copy2(TEMPLATE, outside)
        _job, backup = oc.set_schedule(oc.load(outside), "ssl-renew.sh",
                                       "30 0 * * *")
        self.assertEqual(os.path.dirname(backup), self.tmp.name)

    def test_a_stray_bak_file_is_moved_not_deleted(self):
        stray = self.path + ".bak_20260101_000000"
        shutil.copy2(TEMPLATE, stray)
        _job, backup = oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")
        self.assertFalse(os.path.exists(stray))
        moved_path = os.path.join(self.backup_dir,
                                  "myodoo-maintenance.bak_20260101_000000")
        self.assertTrue(os.path.exists(moved_path))
        self.assertEqual(backup.moved, [moved_path])

    def test_a_collision_keeps_both(self):
        stray = self.path + ".bak_20260101_000000"
        shutil.copy2(TEMPLATE, stray)
        os.makedirs(self.backup_dir, mode=0o700, exist_ok=True)
        existing = os.path.join(self.backup_dir,
                                "myodoo-maintenance.bak_20260101_000000")
        shutil.copy2(TEMPLATE, existing)

        oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")

        self.assertTrue(os.path.exists(existing))
        self.assertTrue(os.path.exists(existing + ".1"))

    def test_an_unrelated_file_in_cron_d_is_untouched(self):
        unrelated = os.path.join(self.cron_d, "other-package")
        with open(unrelated, "w", encoding="utf-8") as handle:
            handle.write("0 3 * * * root /usr/bin/true\n")

        oc.set_schedule(self.load(), "ssl-renew.sh", "30 0 * * *")

        self.assertTrue(os.path.exists(unrelated))


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


# ==============================================================================
# Interactive menu — bare `docron` on a real terminal (v1.2.0)
# ==============================================================================

class GroupByScriptTest(CronFixture):
    """Pure grouping helper behind the menu - no terminal involved."""

    def entry(self, cron, script):
        return {e.script: e for e in oc.group_by_script(cron.jobs)}[script]

    def test_the_two_backup_lines_become_one_entry(self):
        entry = self.entry(self.load(), "container2backup.py")
        self.assertEqual(len(entry.jobs), 2)
        self.assertEqual(entry.state, "on")
        self.assertEqual(entry.mark, "✓")
        self.assertEqual(entry.display, "container2backup")

    def test_a_single_line_script_is_its_own_entry(self):
        entry = self.entry(self.load(), "ssl-renew.sh")
        self.assertEqual(len(entry.jobs), 1)
        self.assertEqual(entry.display, "ssl-renew.sh")

    def test_switching_one_of_two_lines_off_is_partial(self):
        oc.set_active(self.load(), "container2backup.py:1", False)
        entry = self.entry(self.load(), "container2backup.py")
        self.assertEqual(entry.state, "partial")
        self.assertEqual(entry.mark, "◐")

    def test_switching_both_lines_off_is_off(self):
        oc.set_active(self.load(), "container2backup.py", False)
        entry = self.entry(self.load(), "container2backup.py")
        self.assertEqual(entry.state, "off")
        self.assertEqual(entry.mark, "•")

    def test_entries_keep_file_order(self):
        scripts = [e.script for e in oc.group_by_script(self.load().jobs)]
        self.assertEqual(scripts[0], "container2backup.py")
        self.assertEqual(len(scripts), 7)  # 8 jobs, 2 of them one script

    def test_menu_lines_number_from_one(self):
        lines = oc.format_menu(oc.group_by_script(self.load().jobs))
        self.assertTrue(lines[0].startswith("1"))
        self.assertIn("container2backup (2 lines)", lines[0])
        self.assertTrue(lines[-1].startswith("7"))


class MenuParsingTest(unittest.TestCase):
    """The bits interactive() delegates to instead of parsing input inline."""

    def test_a_valid_number_is_zero_based(self):
        self.assertEqual(oc._parse_menu_choice("1", 7), 0)
        self.assertEqual(oc._parse_menu_choice(" 7 \n", 7), 6)

    def test_out_of_range_is_invalid(self):
        self.assertIsNone(oc._parse_menu_choice("0", 7))
        self.assertIsNone(oc._parse_menu_choice("8", 7))

    def test_non_numeric_is_invalid(self):
        self.assertIsNone(oc._parse_menu_choice("abc", 7))
        self.assertIsNone(oc._parse_menu_choice("", 7))

    def test_yes_answers(self):
        for answer in ("j", "J", "ja", "Ja", "y", "Y", "yes", " j \n"):
            self.assertTrue(oc._is_yes(answer), answer)

    def test_no_answers(self):
        for answer in ("n", "nein", "", "\n", "x"):
            self.assertFalse(oc._is_yes(answer), answer)


class InteractiveTest(CronFixture):
    """Drives interactive() with StringIO - no real TTY needed, per the
    module's design (streams are parameters, not sys.stdin/sys.stdout)."""

    def run_interactive(self, script):
        stdin = io.StringIO(script)
        stdout = io.StringIO()
        code = oc.interactive(self.path, stdin, stdout)
        return code, stdout.getvalue()

    def test_switching_entry_one_off_writes_both_backup_lines(self):
        code, out = self.run_interactive("1\nj\n\n")
        self.assertEqual(code, 0)
        cron = self.load()
        self.assertFalse(cron.job("container2backup.py:1").active)
        self.assertFalse(cron.job("container2backup.py:2").active)
        self.assertIn("container2backup.py:1 abgeschaltet", out)
        self.assertIn("container2backup.py:2 abgeschaltet", out)
        self.assertIn("Rückgängig machen: docron --enable <name>", out)

    def test_declining_with_capital_n_writes_nothing(self):
        code, out = self.run_interactive("1\nN\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.text(), self.original)
        self.assertNotIn("Rückgängig machen", out)

    def test_empty_confirmation_answer_is_no(self):
        code, out = self.run_interactive("1\n\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.text(), self.original)

    def test_off_switch_shows_the_backup_explanation(self):
        _code, out = self.run_interactive("1\nN\n")
        self.assertIn("dostat Backup als „off“", out)

    def test_partial_entry_choice_switches_everything_on(self):
        oc.set_active(self.load(), "container2backup.py:1", False)
        code, out = self.run_interactive("1\nj\n\n")
        self.assertEqual(code, 0)
        cron = self.load()
        self.assertTrue(cron.job("container2backup.py:1").active)
        self.assertTrue(cron.job("container2backup.py:2").active)
        self.assertIn("einschalten", out)
        # Turning something on never shows the "off" consequence explanation.
        self.assertNotIn("dostat Backup als", out)

    def test_invalid_input_reprompts_and_recovers(self):
        code, out = self.run_interactive("abc\n99\n\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("Ungültige Eingabe"), 2)
        self.assertEqual(self.text(), self.original)

    def test_eof_on_the_menu_prompt_exits_cleanly(self):
        code, out = self.run_interactive("")
        self.assertEqual(code, 0)
        self.assertEqual(self.text(), self.original)

    def test_eof_during_confirmation_exits_cleanly(self):
        code, out = self.run_interactive("1\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.text(), self.original)


class TtyDispatchTest(CronFixture):
    """main()'s gate between the plain report and the interactive menu -
    a fake stream's isatty() stands in for a real terminal."""

    class _FakeStream(io.StringIO):
        def __init__(self, initial="", tty=True):
            super().__init__(initial)
            self._tty = tty

        def isatty(self):
            return self._tty

    def call_main(self, argv, stdin_tty, stdout_tty, stdin_text=""):
        fake_in = self._FakeStream(stdin_text, tty=stdin_tty)
        fake_out = self._FakeStream(tty=stdout_tty)
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = fake_in, fake_out
        try:
            code = oc.main(argv)
        finally:
            sys.stdin, sys.stdout = old_in, old_out
        return code, fake_out.getvalue()

    def test_non_tty_bare_call_prints_report_without_prompt(self):
        code, out = self.call_main(["--path", self.path],
                                    stdin_tty=False, stdout_tty=False)
        self.assertEqual(code, 0)
        self.assertIn("Maintenance cron", out)
        self.assertNotIn(oc.MENU_PROMPT, out)

    def test_tty_bare_call_shows_the_menu(self):
        code, out = self.call_main(["--path", self.path],
                                    stdin_tty=True, stdout_tty=True, stdin_text="")
        self.assertEqual(code, 0)
        self.assertIn(oc.MENU_PROMPT, out)

    def test_no_input_suppresses_the_menu_even_on_a_tty(self):
        code, out = self.call_main(["--path", self.path, "--no-input"],
                                    stdin_tty=True, stdout_tty=True, stdin_text="")
        self.assertEqual(code, 0)
        self.assertIn("Maintenance cron", out)
        self.assertNotIn(oc.MENU_PROMPT, out)

    def test_brief_never_prompts_even_on_a_tty(self):
        code, out = self.call_main(["--path", self.path, "--brief"],
                                    stdin_tty=True, stdout_tty=True, stdin_text="")
        self.assertEqual(code, 0)
        self.assertNotIn(oc.MENU_PROMPT, out)

    def test_a_mutation_flag_never_prompts_even_on_a_tty(self):
        code, out = self.call_main(
            ["--path", self.path, "--disable", "nightly-cleanup.sh"],
            stdin_tty=True, stdout_tty=True, stdin_text="")
        self.assertEqual(code, 0)
        self.assertNotIn(oc.MENU_PROMPT, out)


if __name__ == "__main__":
    unittest.main()
