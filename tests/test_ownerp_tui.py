"""
Tests for the selection state of ownerp_tui.py.

The curses drawing layer is deliberately not tested - it is kept thin enough
that there is nothing in it to assert. Everything worth asserting lives in
UpdateSelection, which never touches a terminal.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_tui -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
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


if __name__ == "__main__":
    unittest.main()
