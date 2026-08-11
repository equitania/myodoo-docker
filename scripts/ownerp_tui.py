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

import os
import sys
import time
import curses
import argparse
import subprocess
from os.path import expanduser, join

# The runner is imported for its history reader and for its path. It lives
# beside this script on a server ($HOME) and in scripts/ in the repository -
# both are covered by adding this file's own directory to the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import update_docker_odoo as runner
except ImportError:          # pragma: no cover - a server always has it
    runner = None

RUNNER_SCRIPT = join(expanduser("~"), "update_docker_odoo.py")
CONFIG_FILE = join(expanduser("~"), "docker2update.yaml")

# Below this the list has no room to be a list.
MIN_SIZE = (80, 20)

TUI_DEFAULT_MARKER = join(expanduser("~"), ".ownerp_tui_default")

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


def preflight(is_tty=None, size=None, term=None):
    """Why this terminal cannot host the TUI, or None when it can.

    Checked before curses is initialised, so a refusal is a plain sentence on
    stderr rather than a traceback from a half-set-up screen. Split out from
    main() because these three refusals are the ones worth asserting.
    """
    is_tty = sys.stdout.isatty() if is_tty is None else is_tty
    if not is_tty:
        return ("No terminal on stdout - the TUI needs one. "
                "Use update_docker_odoo.py directly (see --help).")

    term = os.environ.get("TERM", "") if term is None else term
    if term in ("", "dumb"):
        return (f"TERM={term or 'unset'} cannot draw a TUI. "
                "Use update_docker_odoo.py directly (see --help).")

    if size is None:
        size = os.get_terminal_size()
        size = (size.columns, size.lines)
    if size[0] < MIN_SIZE[0] or size[1] < MIN_SIZE[1]:
        return (f"Window too small (currently {size[0]}x{size[1]}, "
                f"need {MIN_SIZE[0]}x{MIN_SIZE[1]}).")
    return None


def format_last_run(entry):
    """One column's worth of 'what happened here last time'."""
    if not entry:
        return "—"
    try:
        when = time.strftime("%d.%m.", time.strptime(entry.get("ts", ""),
                                                     runner.HISTORY_TS_FORMAT))
    except (ValueError, TypeError, AttributeError):
        when = "?"
    text = f"{when} {entry.get('mode', '?')}  {entry.get('result', '?')}"
    comment = entry.get("comment") or ""
    return f'{text}  "{comment}"' if comment else text


def tui_is_default(marker=TUI_DEFAULT_MARKER):
    """Whether `doup` should start the TUI on this server."""
    return os.path.exists(marker)


def set_tui_default(enabled, marker=TUI_DEFAULT_MARKER):
    """Create or remove the marker `doup` looks for. Never raises."""
    try:
        if enabled:
            with open(marker, "w", encoding="utf8") as handle:
                handle.write(f"Set by ownerp_tui.py {SCRIPT_VERSION} on "
                             f"{time.strftime('%d.%m.%Y %H:%M:%S')}\n")
        elif os.path.exists(marker):
            os.remove(marker)
    except OSError as exc:
        print(f"Could not change the doup default: {exc}", file=sys.stderr)


def load_containers(path=CONFIG_FILE):
    """Read the container list. Returns (containers, error_message).

    Read-only, always: this script has no write path into the YAML and must not
    grow one. A parse error comes back as a sentence with its line number
    rather than a traceback - the operator's next move is to open the file at
    that line, and a stack trace does not help them find it.
    """
    import yaml
    try:
        with open(path, encoding="utf8") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return [], f"Configuration not found: {path}"
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        return [], f"{path} cannot be parsed{where}: {getattr(exc, 'problem', exc)}"
    except OSError as exc:
        return [], f"{path} cannot be read: {exc}"
    containers = config.get("containers") or []
    if not containers:
        return [], f"{path} lists no containers."
    return containers, None


HELP_LINES = [
    "  ↑ ↓ / j k   move            Space   select / unselect",
    "  a           all / none      m       mode  M → F → N",
    "  c           run comment     Enter   start the selected systems",
    "  v           validate the configuration",
    "  d           use the TUI as the default for `doup` on this server",
    "  q / Esc     quit",
    "",
    "  M  module copy (2-3 min)   F  full update (10-20 min)",
    "  N  neutralize, then full update - destructive, asks twice",
    "",
    "  Nothing here is ever written to docker2update.yaml. The ticks and modes",
    "  are read from `active:` and `type:` as a starting point, and changing",
    "  them applies to this run only.",
]


def draw(stdscr, selection, latest, message=""):
    """Render the list. Kept deliberately dumb - all state lives elsewhere."""
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    stdscr.addnstr(0, 0, " ownERP Update".ljust(width - 1), width - 1,
                   curses.A_REVERSE)
    header_right = f"{CONFIG_FILE} "
    if len(header_right) < width - 20:
        stdscr.addnstr(0, width - 1 - len(header_right), header_right,
                       len(header_right), curses.A_REVERSE)

    # One line for the header, one for the footer, one for the message.
    visible = max(1, height - 4)
    first = max(0, min(selection.cursor - visible + 1, len(selection.rows) - visible))
    first = max(0, first)

    for offset, row in enumerate(selection.rows[first:first + visible]):
        index = first + offset
        mark = "x" if row["selected"] else " "
        version = f"v{row['version']}" if row["version"] else ""
        line = (f" [{mark}] {row['name']:<18.18} {row['mode']}   {version:<5.5} "
                f"{format_last_run(latest.get(row['name']))}")
        attr = curses.A_BOLD if index == selection.cursor else curses.A_NORMAL
        stdscr.addnstr(2 + offset, 0, line.ljust(width - 1), width - 1, attr)

    if message:
        stdscr.addnstr(height - 2, 0, f" {message}"[:width - 1], width - 1,
                       curses.A_BOLD)
    footer = (" Space select   m mode   c comment   Enter start   "
              "v validate   ? help   q quit")
    stdscr.addnstr(height - 1, 0, footer.ljust(width - 1), width - 1,
                   curses.A_REVERSE)
    stdscr.refresh()


def prompt(stdscr, question, default=""):
    """Read one line from the operator. Returns None when cancelled."""
    height, width = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    try:
        stdscr.addnstr(height - 2, 0, f" {question} ".ljust(width - 1), width - 1,
                       curses.A_BOLD)
        stdscr.move(height - 2, len(question) + 2)
        stdscr.clrtoeol()
        raw = stdscr.getstr(height - 2, len(question) + 2, 120)
    except KeyboardInterrupt:
        return None
    finally:
        curses.noecho()
        curses.curs_set(0)
    return raw.decode("utf8", errors="replace").strip() or default


def confirm(stdscr, lines, question):
    """Show a block and ask for y/n. Returns True only on an explicit yes."""
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for index, line in enumerate(lines[:height - 3]):
        stdscr.addnstr(1 + index, 2, line, width - 3)
    stdscr.addnstr(height - 2, 2, f"{question} (y/N) ", width - 3, curses.A_BOLD)
    stdscr.refresh()
    return stdscr.getch() in (ord("y"), ord("Y"))


def show_block(stdscr, lines):
    """Show a block of text until a key is pressed."""
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for index, line in enumerate(lines[:height - 3]):
        stdscr.addnstr(1 + index, 2, line, width - 3)
    stdscr.addnstr(height - 2, 2, "Press any key.", width - 3, curses.A_BOLD)
    stdscr.refresh()
    stdscr.getch()


def run_outside_curses(stdscr, invocations):
    """Leave curses, run the invocations in order, return the worst exit code.

    Sequential and never parallel: two docker builds on one host compete for
    the same disk and the same daemon, and the run logs would interleave on
    screen. A failing group does not stop the following ones - the operator
    selected them - but its exit code survives to the end.

    The screen is restored explicitly in a finally block. endwin() only
    suspends curses, and while a following refresh() usually revives it, the
    input modes (noecho, cbreak, cursor visibility) are not guaranteed to come
    back with it - and a list that echoes every keystroke is worse than no
    list at all.
    """
    curses.endwin()
    worst = 0
    try:
        for argv in invocations:
            print(f"\n$ {' '.join(argv)}\n", flush=True)
            worst = max(worst, subprocess.call([sys.executable] + argv))
        print("\nDone. Press Enter to return to the list.", flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
    finally:
        stdscr.clear()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.refresh()
    return worst


def loop(stdscr, selection, latest):
    """The key loop. Returns the worst exit code of everything it started."""
    curses.curs_set(0)
    message = ""
    worst = 0

    while True:
        draw(stdscr, selection, latest, message)
        message = ""
        key = stdscr.getch()

        if key in (ord("q"), 27):                      # 27 = Esc
            return worst
        if key == curses.KEY_RESIZE:
            continue
        if key in (curses.KEY_UP, ord("k")):
            selection.move(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selection.move(1)
        elif key == ord(" "):
            selection.toggle()
        elif key == ord("a"):
            selection.toggle_all()
        elif key == ord("m"):
            selection.rotate_mode()
        elif key == ord("c"):
            answer = prompt(stdscr, "Comment for this run:", selection.comment)
            if answer is not None:
                selection.comment = answer
        elif key == ord("d"):
            set_tui_default(not tui_is_default())
            message = ("`doup` now starts the TUI." if tui_is_default()
                       else "`doup` now starts the runner directly.")
        elif key in (ord("?"), ord("h")):
            show_block(stdscr, HELP_LINES)
        elif key == ord("v"):
            worst = max(worst, run_outside_curses(
                stdscr, [[RUNNER_SCRIPT, "--validate"]]))
        elif key in (curses.KEY_ENTER, 10, 13):
            if not selection.can_start():
                message = "Nothing selected - Space ticks a system."
                continue
            summary = ["This run:", ""]
            summary += [f"  {row['name']:<20} {MODE_LABELS[row['mode']]}"
                        for row in selection.selected_rows]
            summary += ["", f'  comment: "{selection.comment}"'
                        if selection.comment else "  no comment"]
            if not confirm(stdscr, summary,
                           f"Start {len(selection.selected_rows)} system(s)?"):
                message = "Cancelled."
                continue
            if selection.needs_extra_confirmation():
                victims = [row for row in selection.selected_rows if row["mode"] == "N"]
                warning = ["NEUTRALIZE - this rewrites the database:", ""]
                warning += [f"  {row['name']}  (database {row['database']})"
                            for row in victims]
                warning += ["", "Mail servers, cron jobs and outgoing interfaces",
                            "are disabled in these databases. On a live system",
                            "this is not what you want."]
                if not confirm(stdscr, warning, "Neutralize these databases?"):
                    message = "Cancelled."
                    continue
            worst = max(worst, run_outside_curses(
                stdscr, selection.runner_invocations(RUNNER_SCRIPT)))
            latest = last_run_by_container(runner.read_history() if runner else [])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Select Odoo container updates and hand them to "
                    "update_docker_odoo.py.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE,
                        help=f"Configuration file (default: {CONFIG_FILE})")
    parser.add_argument("--make-default", action="store_true",
                        help="Let `doup` start this TUI on an interactive terminal")
    parser.add_argument("--no-default", action="store_true",
                        help="Let `doup` start the runner directly again")
    args = parser.parse_args(argv)

    if args.make_default or args.no_default:
        set_tui_default(args.make_default)
        print("`doup` now starts the TUI." if tui_is_default()
              else "`doup` now starts the runner directly.")
        return 0

    refusal = preflight()
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    containers, error = load_containers(args.config)
    if error:
        print(error, file=sys.stderr)
        print(f"Open it with: mcedit {args.config}", file=sys.stderr)
        return 1

    selection = UpdateSelection(containers)
    latest = last_run_by_container(runner.read_history() if runner else [])
    # curses.wrapper restores the terminal on any exit, exception included - a
    # wrecked terminal after a crash is what operators hold against TUIs.
    return curses.wrapper(loop, selection, latest)


if __name__ == "__main__":
    sys.exit(main())
