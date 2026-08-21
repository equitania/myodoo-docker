"""
Tests for muting readiness findings.

A muted check still runs and still says what it found; only its weight
changes. The tests below pin the three things that make that honest: the
line stays visible in the full report, it never reaches --brief or the exit
code, and the count of muted findings can never be suppressed. A mute that
could hide its own existence would be a way to make a server look healthy.

Run from the repository root:

    python3 -m unittest tests.test_readiness_mute -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import importlib.util  # noqa: E402

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server-readiness.py")
_spec = importlib.util.spec_from_file_location("server_readiness", _PATH)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def render(findings, mode="full"):
    stream = io.StringIO()
    sr.print_report(findings, mode, stream)
    return stream.getvalue()


class MutedSeverityTest(unittest.TestCase):
    def setUp(self):
        self.fail_finding = sr.Finding(
            "backup_recency", sr.Severity.FAIL, "Backup recency",
            "last backup activity 34.9 d ago", "dobk")
        self.ok_finding = sr._ok("logrotate_present", "Logrotate", "installed")

    def test_muting_keeps_the_original_text(self):
        muted = sr.mute_finding(self.fail_finding, "test server, no backups")
        self.assertIs(muted.severity, sr.Severity.MUTED)
        self.assertEqual(muted.detail, "last backup activity 34.9 d ago")
        self.assertEqual(muted.note, "test server, no backups")

    def test_muting_drops_the_fix(self):
        """The fix is advice to act. On a muted finding nobody should act."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertIsNone(muted.fix)

    def test_the_full_report_shows_the_line_and_the_reason(self):
        muted = sr.mute_finding(self.fail_finding, "test server, no backups")
        text = render([muted, self.ok_finding], "full")
        self.assertIn("[MUTED]", text)
        self.assertIn("Backup recency", text)
        self.assertIn("test server, no backups", text)
        self.assertNotIn("Fix:", text)

    def test_brief_hides_the_line(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        text = render([muted, self.ok_finding], "brief")
        self.assertNotIn("Backup recency", text)

    def test_brief_never_hides_the_count(self):
        """A report that omits part of itself without saying so is a lie."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        for mode in ("full", "brief"):
            self.assertIn("1 muted", render([muted, self.ok_finding], mode))

    def test_quiet_stays_silent_when_the_only_problem_is_muted(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertEqual(render([muted, self.ok_finding], "quiet"), "")

    def test_a_muted_fail_does_not_set_the_exit_code(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertFalse(any(f.severity is sr.Severity.FAIL
                             for f in [muted, self.ok_finding]))

    def test_the_label_column_still_lines_up(self):
        """[MUTED] is three characters wider than [OK]; the detail column of
        every row must still start in the same place."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        lines = [l for l in render([muted, self.ok_finding], "full").splitlines()
                 if "Backup recency" in l or "Logrotate" in l]
        self.assertEqual(len(lines), 2)
        columns = [line.index("Backup recency") if "Backup recency" in line
                   else line.index("Logrotate") for line in lines]
        self.assertEqual(columns[0], columns[1])


class MuteFixture(unittest.TestCase):
    """A throwaway home, so nothing here depends on a real server."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.ctx = sr.HealthContext(root=self.home, home=self.home,
                                    repo=os.path.join(self.home, "myodoo-docker"))

    def write_mutes(self, text):
        path = sr.mutes_path(self.ctx)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class ReadMutesTest(MuteFixture):
    def test_no_file_is_not_an_error(self):
        self.assertEqual(sr.read_mutes(self.ctx), [])

    def test_a_plain_entry_is_read(self):
        self.write_mutes("certbot_timer_window | 2026-08-21 | own certificates\n")
        entries = sr.read_mutes(self.ctx)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].check_id, "certbot_timer_window")
        self.assertEqual(entries[0].since, "2026-08-21")
        self.assertEqual(entries[0].reason, "own certificates")

    def test_comments_and_blank_lines_are_ignored(self):
        self.write_mutes("# a comment\n\n  \nbackup_recency | 2026-08-21 | test server\n")
        self.assertEqual([e.check_id for e in sr.read_mutes(self.ctx)],
                         ["backup_recency"])

    def test_surrounding_whitespace_is_stripped(self):
        """The file is column-aligned by the writer and by hand."""
        self.write_mutes("backup_recency       | 2026-08-21 | test server  \n")
        entry = sr.read_mutes(self.ctx)[0]
        self.assertEqual(entry.check_id, "backup_recency")
        self.assertEqual(entry.reason, "test server")

    def test_a_reason_may_contain_a_pipe(self):
        """Split on the first two separators only — the reason is free text."""
        self.write_mutes("backup_recency | 2026-08-21 | test | staging box\n")
        self.assertEqual(sr.read_mutes(self.ctx)[0].reason, "test | staging box")

    def test_a_malformed_line_is_skipped_not_fatal(self):
        """One bad hand-edit must not cost the operator every other mute."""
        self.write_mutes("nonsense\nbackup_recency | 2026-08-21 | test server\n")
        self.assertEqual([e.check_id for e in sr.read_mutes(self.ctx)],
                         ["backup_recency"])

    def test_an_unreadable_file_yields_nothing_rather_than_raising(self):
        path = self.write_mutes("backup_recency | 2026-08-21 | test\n")
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o600)
        if os.geteuid() == 0:
            self.skipTest("root reads regardless of mode")
        self.assertEqual(sr.read_mutes(self.ctx), [])

    def test_the_path_is_built_from_the_context_not_from_root(self):
        self.assertTrue(sr.mutes_path(self.ctx).startswith(self.home))


class ApplyMutesTest(MuteFixture):
    """run_checks() against a throwaway tree: almost everything FAILs or SKIPs
    there, which is fine — these tests only ask what muting did to the result."""

    def find(self, findings, check_id):
        for finding in findings:
            if finding.check_id == check_id:
                return finding
        self.fail(f"no finding with check_id {check_id!r}")

    def test_a_muted_check_comes_back_muted(self):
        self.write_mutes("maintenance_cron_present | 2026-08-21 | not scheduled here\n")
        finding = self.find(sr.run_checks(self.ctx), "maintenance_cron_present")
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("not scheduled here", finding.note)
        self.assertIn("2026-08-21", finding.note)

    def test_an_unmuted_check_is_untouched(self):
        self.write_mutes("maintenance_cron_present | 2026-08-21 | not scheduled here\n")
        finding = self.find(sr.run_checks(self.ctx), "logrotate_present")
        self.assertIsNot(finding.severity, sr.Severity.MUTED)

    def test_without_a_mute_file_nothing_is_muted(self):
        findings = sr.run_checks(self.ctx)
        self.assertFalse(any(f.severity is sr.Severity.MUTED for f in findings))

    def test_no_registry_finding_when_every_entry_resolves(self):
        self.write_mutes("logrotate_present | 2026-08-21 | not used here\n")
        ids = [f.check_id for f in sr.run_checks(self.ctx)]
        self.assertNotIn("mute_registry", ids)

    def test_a_stale_entry_is_reported(self):
        """The silent failure this prevents: the message comes back one day and
        the file still looks like it should be stopping it."""
        self.write_mutes("backup_freshness | 2026-08-21 | renamed long ago\n")
        finding = self.find(sr.run_checks(self.ctx), "mute_registry")
        self.assertIs(finding.severity, sr.Severity.WARN)
        self.assertIn("backup_freshness", finding.detail)
        self.assertIn("ownerp_mute.py --unmute", finding.fix)

    def test_the_registry_guard_cannot_mute_itself(self):
        self.write_mutes("backup_freshness | 2026-08-21 | renamed\n"
                         "mute_registry | 2026-08-21 | stop nagging\n")
        finding = self.find(sr.run_checks(self.ctx), "mute_registry")
        self.assertIs(finding.severity, sr.Severity.WARN)


class DerivedMuteTest(MuteFixture):
    """A backup check on a host where the backup job is switched off on purpose.

    ownerp_cron.py parks a disabled job behind a marker instead of deleting it,
    so the cron file already records the decision. Reading it beats asking the
    operator to state the same fact a second time in a second file.
    """

    def install_cron(self, body):
        path = self.ctx.p(sr.CRON_DEST)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    def backup_finding(self):
        for finding in sr.run_checks(self.ctx):
            if finding.check_id == "backup_recency":
                return finding
        self.fail("no backup_recency finding")

    def test_a_disabled_backup_job_mutes_the_backup_check(self):
        self.install_cron(
            "#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n"
            "0 0 * * * root /root/ssl-renew.sh\n")
        finding = self.backup_finding()
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("cron job disabled", finding.note)

    def test_an_active_backup_job_does_not_mute_it(self):
        self.install_cron("0 2 * * * root /root/container2backup.py\n")
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_another_disabled_job_does_not_mute_the_backup_check(self):
        """No blanket muting: only the pair whose absence explains the finding."""
        self.install_cron(
            "#OWNERP-DISABLED# 0 0 * * * root /root/ssl-renew.sh\n"
            "0 2 * * * root /root/container2backup.py\n")
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_no_cron_file_at_all_does_not_mute_it(self):
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_an_explicit_mute_wins_over_the_derived_one(self):
        """Both true at once: the operator's own words are the better message."""
        self.install_cron(
            "#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n")
        self.write_mutes("backup_recency | 2026-08-21 | staging, never backed up\n")
        finding = self.backup_finding()
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("staging, never backed up", finding.note)


class MutedListingTest(MuteFixture):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sr.main(["--home", self.home, "--root", self.home, *args])
        return code, out.getvalue()

    def test_muted_lists_the_explicit_entries(self):
        self.write_mutes("certbot_timer_window | 2026-08-21 | own certificates\n")
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("certbot_timer_window", text)
        self.assertIn("own certificates", text)
        self.assertIn("2026-08-21", text)

    def test_muted_says_so_when_nothing_is_muted(self):
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("no checks are muted", text.lower())

    def test_muted_names_a_derived_mute_as_derived(self):
        """Otherwise an operator looks for it in the file and does not find it."""
        path = self.ctx.p(sr.CRON_DEST)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n")
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("backup_recency", text)
        self.assertIn("cron job disabled", text)

    def test_muted_never_writes(self):
        before = sorted(os.listdir(self.home))
        self.run_cli("--muted")
        self.assertEqual(sorted(os.listdir(self.home)), before)

    def test_muted_exits_zero_even_with_a_failing_check(self):
        """It is a listing, not a verdict."""
        self.assertEqual(self.run_cli("--muted")[0], 0)
