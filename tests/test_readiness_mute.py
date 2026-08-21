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

import io
import os
import sys
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
