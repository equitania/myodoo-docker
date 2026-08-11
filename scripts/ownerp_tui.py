#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Terminal UI for selecting Odoo container updates
# Version 1.0.0
# Date 11.08.2026
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
#    Copyright (C) 2014-now Equitania Software GmbH(<http://www.equitania.de>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
"""Pick the systems for an ad-hoc update, then hand the work to the runner.

This script decides nothing about updating and executes nothing itself. It
selects - which systems, in which mode, with which comment - and then leaves
curses and starts update_docker_odoo.py as a subprocess. The runner keeps its
logging, its run log and its exit code; wrapping a twenty-minute build in a
curses window would mean rebuilding all of that inside a pad nobody can scroll.

It never writes to docker2update.yaml. `active:` and `type:` are read as the
pre-selection and nothing else - that is what makes it safe to change them for
one run.
"""

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "11.08.2026"

# The update modes, in the order the 'm' key rotates them.
MODES = ("M", "F", "N")

MODE_LABELS = {
    "M": "Module copy",
    "F": "Full update",
    "N": "Neutralize and update",
}


def last_run_by_container(entries):
    """Map container name -> its newest history entry.

    Takes the list read_history() returns (newest first), so the first entry
    seen for a name is the one to keep.
    """
    latest = {}
    for item in entries:
        name = item.get("container")
        if name and name not in latest:
            latest[name] = item
    return latest


class UpdateSelection:
    """What the operator has picked: systems, modes, and one comment.

    Deliberately free of curses. Everything worth asserting lives here, which
    keeps the drawing code thin enough that there is nothing in it to test.
    """

    def __init__(self, containers):
        self.rows = []
        for container in containers:
            mode = str(container.get('type', 'F') or 'F').upper()
            self.rows.append({
                "name": container.get('container_name', 'unknown'),
                "database": container.get('database_name', ''),
                "version": str(container.get('odoo_version', '') or ''),
                # An unusable type falls back to F rather than refusing to
                # start: the operator can see and change the mode on screen.
                "mode": mode if mode in MODES else "F",
                "selected": bool(container.get('active', True)),
            })
        self.comment = ""
        self.cursor = 0

    # -- navigation and selection -----------------------------------------

    def move(self, delta):
        if self.rows:
            self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def toggle(self, index=None):
        if self.rows:
            row = self.rows[self.cursor if index is None else index]
            row["selected"] = not row["selected"]

    def toggle_all(self):
        """Select everything - or clear it, when everything already is."""
        target = not all(row["selected"] for row in self.rows) if self.rows else False
        for row in self.rows:
            row["selected"] = target

    def rotate_mode(self, index=None):
        if self.rows:
            row = self.rows[self.cursor if index is None else index]
            row["mode"] = MODES[(MODES.index(row["mode"]) + 1) % len(MODES)]

    # -- what the runner is asked to do -----------------------------------

    @property
    def selected_rows(self):
        return [row for row in self.rows if row["selected"]]

    def can_start(self):
        return bool(self.selected_rows)

    def needs_extra_confirmation(self):
        """True when the run neutralizes a database.

        Neutralizing is destructive - it rewrites mail servers, cron and
        outgoing interfaces - and must never be one keystroke away from a typo.
        """
        return any(row["mode"] == "N" for row in self.selected_rows)

    def runner_invocations(self, script):
        """One argument list per mode group, in the order of the list.

        --type applies to a whole invocation, so a selection with mixed modes
        becomes several runs. Grouping here rather than inventing a
        per-container flag syntax keeps -s the same thing an operator types by
        hand.
        """
        groups = []                        # [(mode, [names])], first appearance wins
        for row in self.selected_rows:
            for mode, names in groups:
                if mode == row["mode"]:
                    names.append(row["name"])
                    break
            else:
                groups.append((row["mode"], [row["name"]]))

        invocations = []
        for mode, names in groups:
            argv = [script, "-s", ",".join(names), "--type", mode]
            if self.comment:
                argv += ["--comment", self.comment]
            invocations.append(argv)
        return invocations
