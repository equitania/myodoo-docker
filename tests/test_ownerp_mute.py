"""
Tests for ownerp_mute.py — the write path for muted readiness checks.

The value of this module is entirely in that write path. Everything it can
get wrong is silent: a half-written file, a mode that leaves credentials-
adjacent config world-readable, an entry without a reason that nobody can
justify a year later. These tests pin the promises that make writing safe.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_mute -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ownerp_mute as om  # noqa: E402


class MuteWriteFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def path(self):
        return om.mutes_path(self.home)

    def text(self):
        with open(self.path(), "r", encoding="utf-8") as handle:
            return handle.read()


class WriteTest(MuteWriteFixture):
    def test_the_first_mute_creates_the_file_and_its_directory(self):
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertTrue(os.path.isfile(self.path()))
        self.assertIn("certbot_timer_window", self.text())
        self.assertIn("own certificates", self.text())

    def test_the_file_is_not_world_readable(self):
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertEqual(os.stat(self.path()).st_mode & 0o777, 0o600)

    def test_the_written_file_reads_back_as_what_went_in(self):
        om.mute(self.home, "backup_recency", "test server | staging")
        entries = om.load(self.home)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].check_id, "backup_recency")
        self.assertEqual(entries[0].reason, "test server | staging")

    def test_a_second_mute_keeps_the_first(self):
        om.mute(self.home, "backup_recency", "test server")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertEqual(sorted(e.check_id for e in om.load(self.home)),
                         ["backup_recency", "certbot_timer_window"])

    def test_muting_the_same_check_twice_replaces_rather_than_duplicates(self):
        om.mute(self.home, "backup_recency", "first reason")
        om.mute(self.home, "backup_recency", "better reason")
        entries = om.load(self.home)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].reason, "better reason")

    def test_a_backup_is_taken_before_overwriting(self):
        om.mute(self.home, "backup_recency", "first reason")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        backups = [n for n in os.listdir(os.path.dirname(self.path()))
                   if ".bak_" in n]
        self.assertEqual(len(backups), 1)

    def test_no_temp_file_is_left_behind(self):
        om.mute(self.home, "backup_recency", "test server")
        leftovers = [n for n in os.listdir(os.path.dirname(self.path()))
                     if ".tmp_" in n]
        self.assertEqual(leftovers, [])

    def test_unmute_removes_only_the_named_entry(self):
        om.mute(self.home, "backup_recency", "test server")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        om.unmute(self.home, "backup_recency")
        self.assertEqual([e.check_id for e in om.load(self.home)],
                         ["certbot_timer_window"])

    def test_unmuting_something_that_is_not_muted_is_an_error(self):
        with self.assertRaises(om.MuteError):
            om.unmute(self.home, "backup_recency")


class RefusalTest(MuteWriteFixture):
    def test_a_mute_without_a_reason_is_refused(self):
        """An entry nobody can justify a year later gets deleted rather than
        understood, which brings the message back on a host that decided
        against it."""
        for reason in ("", "   "):
            with self.assertRaises(om.MuteError):
                om.mute(self.home, "backup_recency", reason)
        self.assertFalse(os.path.exists(self.path()))

    def test_an_unknown_check_id_is_refused_when_the_ids_are_known(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup_freshness", "typo",
                    valid_ids=["backup_recency", "certbot_timer_window"])
        self.assertFalse(os.path.exists(self.path()))

    def test_the_error_names_the_valid_ids(self):
        with self.assertRaises(om.MuteError) as caught:
            om.mute(self.home, "backup_freshness", "typo",
                    valid_ids=["backup_recency"])
        self.assertIn("backup_recency", str(caught.exception))

    def test_an_unmutable_id_is_refused(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "mute_registry", "stop nagging",
                    valid_ids=["mute_registry"])

    def test_a_separator_in_the_check_id_is_refused(self):
        """It would produce a line that parses back as something else."""
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup | recency", "test")

    def test_a_newline_in_the_reason_is_refused(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup_recency", "line one\nline two")


class AtomicityTest(MuteWriteFixture):
    def test_a_failed_validation_leaves_the_original_byte_identical(self):
        om.mute(self.home, "backup_recency", "test server")
        before = self.text()

        original_verify = om._verify

        def refuse(*args, **kwargs):
            raise om.MuteError("simulated validation failure")

        om._verify = refuse
        self.addCleanup(setattr, om, "_verify", original_verify)

        with self.assertRaises(om.MuteError):
            om.mute(self.home, "certbot_timer_window", "own certificates")

        self.assertEqual(self.text(), before)
        leftovers = [n for n in os.listdir(os.path.dirname(self.path()))
                     if ".tmp_" in n]
        self.assertEqual(leftovers, [])


class CliTest(MuteWriteFixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = om.main(["--home", self.home, *args])
        return code, out.getvalue() + err.getvalue()

    def test_list_on_an_empty_host_says_so_and_succeeds(self):
        code, text = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("no checks are muted", text.lower())

    def test_mute_then_list_shows_the_entry(self):
        self.assertEqual(self.run_cli("backup_recency", "--reason",
                                      "test server", "--no-verify-id")[0], 0)
        code, text = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("backup_recency", text)
        self.assertIn("test server", text)

    def test_mute_without_a_reason_exits_1_and_writes_nothing(self):
        code, text = self.run_cli("backup_recency", "--no-verify-id")
        self.assertEqual(code, 1)
        self.assertIn("reason", text.lower())
        self.assertFalse(os.path.exists(self.path()))

    def test_unmute_reports_when_nothing_was_muted(self):
        code, text = self.run_cli("--unmute", "backup_recency")
        self.assertEqual(code, 1)
        self.assertIn("not muted", text.lower())

    def test_a_successful_write_names_the_backup_or_says_it_was_new(self):
        self.run_cli("backup_recency", "--reason", "test", "--no-verify-id")
        code, text = self.run_cli("certbot_timer_window", "--reason", "own certs",
                                  "--no-verify-id")
        self.assertEqual(code, 0)
        self.assertIn("backup", text.lower())
