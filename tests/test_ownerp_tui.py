"""
Tests for the selection state of ownerp_tui.py.

The curses drawing layer is deliberately not tested - it is kept thin enough
that there is nothing in it to assert. Everything worth asserting lives in
UpdateSelection, which never touches a terminal.

Standard library only, like the rest of the suite. PyYAML is imported at module
level by update_docker_odoo.py, which ownerp_tui.py in turn imports, so a
placeholder module stands in when it is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_tui -v
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import ownerp_tui as tui  # noqa: E402

CONTAINERS = [
    {"container_name": "live-odoo", "database_name": "live_db",
     "odoo_version": "18", "type": "F", "active": True},
    {"container_name": "test-odoo", "database_name": "test_db",
     "odoo_version": "18", "type": "M", "active": False},
    {"container_name": "demo-odoo", "database_name": "demo_db",
     "odoo_version": "16", "type": "N", "active": False},
]


class PreselectionTest(unittest.TestCase):
    def test_active_containers_start_selected(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual([row["selected"] for row in selection.rows],
                         [True, False, False])

    def test_the_mode_comes_from_the_yaml_type(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual([row["mode"] for row in selection.rows], ["F", "M", "N"])

    def test_a_missing_active_key_counts_as_active(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "F"}])
        self.assertTrue(selection.rows[0]["selected"])

    def test_an_unusable_type_falls_back_to_full(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "X"}])
        self.assertEqual(selection.rows[0]["mode"], "F")

    def test_a_lowercase_type_is_accepted(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "m"}])
        self.assertEqual(selection.rows[0]["mode"], "M")


class NavigationTest(unittest.TestCase):
    def setUp(self):
        self.selection = tui.UpdateSelection(CONTAINERS)

    def test_the_cursor_stops_at_the_top(self):
        self.selection.move(-5)
        self.assertEqual(self.selection.cursor, 0)

    def test_the_cursor_stops_at_the_bottom(self):
        self.selection.move(99)
        self.assertEqual(self.selection.cursor, len(CONTAINERS) - 1)

    def test_moving_an_empty_list_leaves_the_cursor_alone(self):
        selection = tui.UpdateSelection([])
        selection.move(1)                             # must not raise
        self.assertEqual(selection.cursor, 0)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.selection = tui.UpdateSelection(CONTAINERS)

    def test_toggling_flips_the_row_under_the_cursor(self):
        self.selection.toggle()
        self.assertFalse(self.selection.rows[0]["selected"])

    def test_toggle_all_selects_everything_when_some_are_unselected(self):
        self.selection.toggle_all()
        self.assertTrue(all(row["selected"] for row in self.selection.rows))

    def test_toggle_all_clears_when_everything_is_selected(self):
        self.selection.toggle_all()
        self.selection.toggle_all()
        self.assertFalse(any(row["selected"] for row in self.selection.rows))

    def test_the_mode_rotates_m_f_n_and_wraps(self):
        self.selection.cursor = 1              # starts at M
        for expected in ("F", "N", "M"):
            self.selection.rotate_mode()
            self.assertEqual(self.selection.rows[1]["mode"], expected)

    def test_an_empty_selection_cannot_start(self):
        self.selection.toggle()                # unselect the only active row
        self.assertFalse(self.selection.can_start())

    def test_a_selection_can_start(self):
        self.assertTrue(self.selection.can_start())


class ConfirmationTest(unittest.TestCase):
    def test_a_neutralize_in_the_selection_needs_extra_confirmation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.cursor = 2                   # demo-odoo, mode N
        selection.toggle()
        self.assertTrue(selection.needs_extra_confirmation())

    def test_an_unselected_neutralize_does_not(self):
        # demo-odoo is mode N but inactive, so it is not part of the run.
        self.assertFalse(tui.UpdateSelection(CONTAINERS).needs_extra_confirmation())


class RunnerInvocationTest(unittest.TestCase):
    SCRIPT = "/root/update_docker_odoo.py"

    def test_one_mode_produces_exactly_one_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual(selection.runner_invocations(self.SCRIPT),
                         [[self.SCRIPT, "-s", "live-odoo", "--type", "F"]])

    def test_containers_of_the_same_mode_share_one_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[2]["mode"] = "F"
        selection.rows[2]["selected"] = True
        self.assertEqual(selection.runner_invocations(self.SCRIPT),
                         [[self.SCRIPT, "-s", "live-odoo,demo-odoo", "--type", "F"]])

    def test_mixed_modes_produce_one_invocation_per_mode(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[1]["selected"] = True
        self.assertEqual(selection.runner_invocations(self.SCRIPT), [
            [self.SCRIPT, "-s", "live-odoo", "--type", "F"],
            [self.SCRIPT, "-s", "test-odoo", "--type", "M"],
        ])

    def test_the_groups_keep_the_order_of_the_list(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[0]["selected"] = False
        selection.rows[1]["selected"] = True
        selection.rows[2]["selected"] = True
        self.assertEqual([argv[4] for argv in selection.runner_invocations(self.SCRIPT)],
                         ["M", "N"])

    def test_the_comment_is_appended_to_every_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[1]["selected"] = True
        selection.comment = "eq_stock nachgezogen"
        for argv in selection.runner_invocations(self.SCRIPT):
            self.assertEqual(argv[-2:], ["--comment", "eq_stock nachgezogen"])

    def test_an_empty_comment_adds_no_flag(self):
        argv = tui.UpdateSelection(CONTAINERS).runner_invocations(self.SCRIPT)[0]
        self.assertNotIn("--comment", argv)

    def test_an_empty_selection_produces_no_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[0]["selected"] = False
        self.assertEqual(selection.runner_invocations(self.SCRIPT), [])

    def test_a_mode_reappearing_after_another_still_joins_its_first_group(self):
        # F, M, F: the two F rows must share one invocation in first-
        # appearance order, and M gets its own - this is the for...else
        # grouping loop's only case not already covered by an adjacent-rows
        # or two-mode test.
        containers = [
            {"container_name": "a", "type": "F", "active": True},
            {"container_name": "b", "type": "M", "active": True},
            {"container_name": "c", "type": "F", "active": True},
        ]
        selection = tui.UpdateSelection(containers)
        self.assertEqual(selection.runner_invocations(self.SCRIPT), [
            [self.SCRIPT, "-s", "a,c", "--type", "F"],
            [self.SCRIPT, "-s", "b", "--type", "M"],
        ])

    def test_a_non_default_config_is_forwarded(self):
        selection = tui.UpdateSelection(CONTAINERS)
        argv = selection.runner_invocations(self.SCRIPT, config="/opt/other.yaml")[0]
        self.assertEqual(argv[:3], [self.SCRIPT, "-c", "/opt/other.yaml"])

    def test_no_config_means_no_c_flag(self):
        argv = tui.UpdateSelection(CONTAINERS).runner_invocations(self.SCRIPT)[0]
        self.assertNotIn("-c", argv)


class LastRunTest(unittest.TestCase):
    ENTRIES = [                                 # newest first, as read_history returns
        {"ts": "2026-08-03T10:00:00", "container": "live-odoo", "mode": "F",
         "result": "ok", "comment": "eq_stock"},
        {"ts": "2026-07-28T10:00:00", "container": "live-odoo", "mode": "M",
         "result": "errors", "comment": ""},
        {"ts": "2026-07-28T09:00:00", "container": "test-odoo", "mode": "M",
         "result": "ok", "comment": ""},
    ]

    def test_only_the_newest_entry_per_container_is_kept(self):
        latest = tui.last_run_by_container(self.ENTRIES)
        self.assertEqual(latest["live-odoo"]["ts"], "2026-08-03T10:00:00")

    def test_every_container_in_the_history_appears(self):
        self.assertEqual(set(tui.last_run_by_container(self.ENTRIES)),
                         {"live-odoo", "test-odoo"})

    def test_an_empty_history_maps_to_nothing(self):
        self.assertEqual(tui.last_run_by_container([]), {})


class PreflightTest(unittest.TestCase):
    """The refusals that must happen before curses is ever initialised.

    stdin_tty is always passed explicitly (True unless it is the thing under
    test) so these do not depend on whether the test runner's own stdin
    happens to be a terminal.
    """

    def test_no_tty_is_refused(self):
        reason = tui.preflight(is_tty=False, size=(120, 40), term="xterm",
                                stdin_tty=True)
        self.assertIn("terminal", reason.lower())

    def test_no_stdin_tty_is_refused(self):
        # stdout can be a terminal while stdin is redirected (e.g. from a
        # file or a pipe) - curses reads keys from stdin, so this must be
        # refused just as clearly as a missing stdout terminal.
        reason = tui.preflight(is_tty=True, size=(120, 40), term="xterm",
                                stdin_tty=False)
        self.assertIn("stdin", reason.lower())
        self.assertIn("update_docker_odoo.py", reason)

    def test_a_dumb_terminal_is_refused(self):
        reason = tui.preflight(is_tty=True, size=(120, 40), term="dumb",
                                stdin_tty=True)
        self.assertIn("TERM", reason)

    def test_a_small_window_is_refused_and_says_the_actual_size(self):
        reason = tui.preflight(is_tty=True, size=(71, 18), term="xterm",
                                stdin_tty=True)
        self.assertIn("71", reason)
        self.assertIn("18", reason)

    def test_a_usable_terminal_passes(self):
        self.assertIsNone(tui.preflight(is_tty=True, size=(80, 20), term="xterm",
                                        stdin_tty=True))

    def test_the_minimum_is_inclusive(self):
        self.assertIsNone(tui.preflight(is_tty=True, size=tui.MIN_SIZE, term="xterm",
                                        stdin_tty=True))


class LastRunFormatTest(unittest.TestCase):
    def test_a_run_is_summarised_as_date_mode_result(self):
        text = tui.format_last_run({"ts": "2026-08-03T10:00:00", "mode": "F",
                                    "result": "ok", "comment": ""})
        self.assertTrue(text.startswith("03.08."))
        self.assertIn("F", text)
        self.assertIn("ok", text)

    def test_a_comment_is_quoted_after_the_result(self):
        text = tui.format_last_run({"ts": "2026-08-03T10:00:00", "mode": "F",
                                    "result": "ok", "comment": "eq_stock"})
        self.assertIn('"eq_stock"', text)

    def test_nothing_known_shows_a_dash(self):
        self.assertEqual(tui.format_last_run(None), "—")

    def test_an_unparsable_timestamp_becomes_a_question_mark(self):
        text = tui.format_last_run({"ts": "yesterday", "mode": "F",
                                    "result": "ok", "comment": ""})
        self.assertTrue(text.startswith("?"))
        self.assertIn("ok", text)


class DefaultMarkerTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.marker = os.path.join(tempfile.mkdtemp(), ".ownerp_tui_default")

    def test_it_is_off_until_the_marker_exists(self):
        self.assertFalse(tui.tui_is_default(self.marker))

    def test_setting_it_creates_the_marker(self):
        tui.set_tui_default(True, self.marker)
        self.assertTrue(tui.tui_is_default(self.marker))

    def test_clearing_it_removes_the_marker(self):
        tui.set_tui_default(True, self.marker)
        tui.set_tui_default(False, self.marker)
        self.assertFalse(tui.tui_is_default(self.marker))

    def test_clearing_an_absent_marker_is_not_an_error(self):
        tui.set_tui_default(False, self.marker)       # must not raise
        self.assertFalse(tui.tui_is_default(self.marker))


if __name__ == "__main__":
    unittest.main()
