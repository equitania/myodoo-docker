#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_console.py
# Description:      The ownERP console: server state, and the configuration
#                   editing that used to mean hand-writing YAML.
# Version:          1.0.0
# Date:             13.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Stage 3 of docs/superpowers/specs/2026-08-13-ownerp-console-design.md.
#
# What it does:
#   Shows what state this server is in, and edits docker2update.yaml,
#   container2backup.yaml and the maintenance cron.
#
# What it deliberately does not do:
#   Start updates. Start backups. Touch containers. Delete anything. That
#   boundary is the design, not an omission: a tool that starts nothing
#   long-running needs no process supervision, no cancel path, no log pane and
#   no partial-failure recovery. Every action here finishes in well under a
#   second or fails with a message. `doup` and `dobk` stay what they are.
#
# It owns no data and no write path:
#   Every fact comes from ownerp_state.py, every configuration change from
#   ownerp_wizard.py, every cron change from ownerp_cron.py. Those already
#   back up, validate and refuse on regression. A second implementation here
#   would be a second place for that sequence to drift out of step - and the
#   one used less often is the one that rots.
#
# Never the only route to anything:
#   dostat, wiz, docron and doval do everything this does, without Textual.
#   That is what makes it safe to depend on a library for the comfortable
#   version. If the library is missing, the message below names those commands
#   rather than leaving an operator stranded.
# ==============================================================================
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
###############################################################################

import os
import sys

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "13.08.2026"

# The dependencies, in one place. Textual is pinned to a major version: it
# moves fast and a widget API is not a stable interface across majors.
#
# PyYAML belongs here even though every ownERP server already has it. `uv run
# --with` builds an ISOLATED environment - the system site-packages are not on
# its path - so a console started that way would find no yaml and report every
# single section as unknown. That failure looks exactly like a broken server,
# which is the worst possible way for a status tool to be wrong.
TEXTUAL_SPEC = "textual>=8,<9"
YAML_SPEC = "pyyaml>=6"
DEPENDENCIES = (TEXTUAL_SPEC, YAML_SPEC)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

NO_TEXTUAL = f"""\
The console needs Textual, and it is not available.

    pip install --user '{TEXTUAL_SPEC}'

Everything the console does also works without it:

    dostat     the state of this server, as text
    wiz        add or change an entry (asks which configuration)
    docron     the maintenance schedule
    doval      check both configurations
"""


def _reexec_through_uv():
    """Restart through `uv run --with textual`, once.

    uv is a prerequisite on every ownERP server, and it caches the resolved
    environment - the network is touched on the first start and not again. The
    guard variable is what keeps a failure from looping: if the re-executed
    process still cannot import Textual, it prints the message and stops.
    """
    import shutil
    import subprocess
    if os.environ.get("OWNERP_CONSOLE_REEXEC"):
        return False
    uv = shutil.which("uv")
    if not uv:
        return False
    environment = dict(os.environ, OWNERP_CONSOLE_REEXEC="1")
    try:
        command = [uv, "run", "--quiet", "--no-project"]
        for spec in DEPENDENCIES:
            command += ["--with", spec]
        command += [sys.executable, os.path.abspath(__file__)] + sys.argv[1:]
        completed = subprocess.run(command, env=environment, check=False)
    except OSError:
        return False
    sys.exit(completed.returncode)


try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import (Button, DataTable, Footer, Header, Input,
                                 Label, Static, TabbedContent, TabPane)
except ImportError:                              # pragma: no cover - by design
    if __name__ == "__main__" and _reexec_through_uv() is False:
        print(NO_TEXTUAL, file=sys.stderr)
        sys.exit(2)
    raise

import importlib.util


def _sibling(name, module_name):
    """Import a sibling script by path, or None. Two carry a hyphen."""
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, os.path.join(HERE, name))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


state = _sibling("ownerp_state.py", "ownerp_state")
wizard = _sibling("ownerp_wizard.py", "ownerp_wizard")
cron = _sibling("ownerp_cron.py", "ownerp_cron")


# ==============================================================================
# Modals
# ==============================================================================

class Confirm(ModalScreen):
    """Yes/no. Returns True only on an explicit yes."""

    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, question, detail=""):
        super().__init__()
        self.question = question
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question, classes="dialog-title")
            if self.detail:
                yield Label(self.detail, classes="dialog-detail")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", id="no")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class EditField(ModalScreen):
    """One field of one entry. Returns the new value, or None on cancel.

    A field at a time rather than a whole-entry form: that is what set_field()
    writes, and a form that collected ten fields and wrote them one by one
    could half-apply. Ten small validated writes with ten chances to refuse
    beats one big one that cannot be rolled back.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, field, current):
        super().__init__()
        self.field = field
        self.current = current

    def compose(self) -> ComposeResult:
        secret = wizard is not None and wizard.validator.redacted(self.field.name)
        with Vertical(classes="dialog"):
            yield Label(self.field.label, classes="dialog-title")
            yield Label(self.field.help, classes="dialog-detail")
            yield Input(
                value="" if secret else str(self.current or ""),
                password=secret,
                placeholder="not shown" if secret else "",
                id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self._save()

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self._save()

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        text = self.query_one("#value", Input).value
        if not text.strip():
            self.notify("A value is required.", severity="warning")
            return
        self.dismiss(text)


class Reschedule(ModalScreen):
    """A cron schedule. Validated here so an impossible one never reaches the file."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, job):
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Schedule for {self.job.job_id}", classes="dialog-title")
            yield Label("minute hour day-of-month month day-of-week",
                        classes="dialog-detail")
            yield Input(value=self.job.schedule, id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self._save()

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self._save()

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        text = self.query_one("#value", Input).value.strip()
        # cron accepts `0 25 * * *` happily and then never fires it. A field
        # count alone would pass exactly the mistake this check exists for.
        problem = cron.validate_schedule(text) if cron else None
        if problem:
            self.notify(problem, severity="error")
            return
        self.dismiss(text)


# ==============================================================================
# The application
# ==============================================================================

class Console(App):
    """Renders, delegates, decides nothing."""

    TITLE = "ownERP"
    CSS = """
    Screen { background: $surface; }
    .dialog {
        width: 70; height: auto; padding: 1 2;
        background: $panel; border: thick $primary;
    }
    .dialog-title { text-style: bold; padding-bottom: 1; }
    .dialog-detail { color: $text-muted; padding-bottom: 1; }
    .dialog-buttons { height: auto; padding-top: 1; align-horizontal: right; }
    .dialog-buttons Button { margin-left: 2; }
    #tiles { grid-size: 2; grid-gutter: 1 2; padding: 1 2; height: auto; }
    .tile { border: round $primary; padding: 0 1; height: auto; min-height: 7; }
    .tile-title { text-style: bold; }
    .unknown { color: $warning; padding: 1 2; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "quit", "Quit", show=False),
    ]

    def __init__(self, home=None, **kwargs):
        super().__init__(**kwargs)
        self.home = home or os.path.expanduser("~")
        self.server = None
        # Row index -> entry index, per table. A table can be sorted or
        # filtered later; addressing the configuration by screen position
        # would then write to the wrong entry.
        self._rows = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("Overview", id="tab-overview"):
                yield Grid(id="tiles")
            with TabPane("Instances", id="tab-instances"):
                yield VerticalScroll(DataTable(id="instances"))
            with TabPane("Backup", id="tab-backup"):
                yield VerticalScroll(DataTable(id="backup"))
            with TabPane("Maintenance", id="tab-maintenance"):
                yield VerticalScroll(DataTable(id="maintenance"))
            with TabPane("System", id="tab-system"):
                yield VerticalScroll(DataTable(id="system"))
        yield Footer()

    def on_mount(self) -> None:
        for table_id, columns in (
                ("instances", ("", "Container", "Database", "Version", "Last run")),
                ("backup", ("", "Database", "Newest", "Size", "Kept", "Keep")),
                ("maintenance", ("", "Job", "Schedule", "Last run")),
                ("system", ("", "Check", "Detail"))):
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_columns(*columns)
            table.cursor_type = "row"
            table.zebra_stripes = True
        self.action_reload()

    # -- data ------------------------------------------------------------

    def action_reload(self) -> None:
        if state is None:
            self.notify("ownerp_state.py is not installed - run ups.",
                        severity="error")
            return
        self.server = state.collect(home=self.home)
        self.sub_title = f"{self.server.hostname}  ·  {state.worst(self.server)}"
        self._fill_tiles()
        self._fill_instances()
        self._fill_backup()
        self._fill_maintenance()
        self._fill_system()

    def _fill_tiles(self) -> None:
        tiles = self.query_one("#tiles", Grid)
        tiles.remove_children()
        server = self.server
        tiles.mount(_tile("Instances", _instance_lines(server.instances)))
        tiles.mount(_tile("Backup", _backup_lines(server.backups)))
        tiles.mount(_tile("Maintenance", _maintenance_lines(server.maintenance)))
        tiles.mount(_tile("System", _system_lines(server.health)))

    def _fill_instances(self) -> None:
        table = self.query_one("#instances", DataTable)
        table.clear()
        self._rows["instances"] = {}
        section = self.server.instances
        if not section.known:
            table.add_row("?", section.error, "", "", "")
            return
        for index, entry in enumerate(section.entries):
            mark = {True: "up", False: "down", None: "?"}[entry.running]
            name = entry.name if entry.active else f"{entry.name} (inactive)"
            key = table.add_row(mark, name, entry.database,
                                entry.version, entry.last_run_text)
            self._rows["instances"][key] = index

    def _fill_backup(self) -> None:
        table = self.query_one("#backup", DataTable)
        table.clear()
        self._rows["backup"] = {}
        section = self.server.backups
        if not section.known:
            table.add_row("?", section.error, "", "", "", "")
            return
        for index, entry in enumerate(section.entries):
            newest = entry.newest
            key = table.add_row(
                {"OK": "ok", "WARN": "!", "FAIL": "XX"}.get(entry.severity, "-"),
                entry.database + (" (sql only)" if entry.only_sql_dump else ""),
                f"{state.human_age(newest.age)} ago" if newest else "none",
                state.human_size(newest.size) if newest else "-",
                str(len(entry.archives)),
                f"{entry.retention_days} d" if entry.retention_days else "-")
            self._rows["backup"][key] = index

    def _fill_maintenance(self) -> None:
        table = self.query_one("#maintenance", DataTable)
        table.clear()
        self._rows["maintenance"] = {}
        section = self.server.maintenance
        if not section.known:
            table.add_row("?", section.error, "", "")
            return
        import time
        for index, job in enumerate(section.jobs):
            last = cron.last_run(job) if cron else None
            key = table.add_row(
                "on" if job.active else "off",
                job.job_id,
                cron.humanise(job.schedule) if cron else job.schedule,
                f"{state.human_age(time.time() - last)} ago" if last else "never")
            self._rows["maintenance"][key] = index

    def _fill_system(self) -> None:
        table = self.query_one("#system", DataTable)
        table.clear()
        section = self.server.health
        if not section.known:
            table.add_row("?", section.error, "")
            return
        for finding in section.findings:
            severity = getattr(finding.severity, "value", finding.severity)
            table.add_row({"OK": "ok", "WARN": "!", "FAIL": "XX"}.get(severity, "-"),
                          finding.title, finding.detail)

    # -- editing ---------------------------------------------------------

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        index = self._rows.get(table_id, {}).get(event.row_key)
        if index is None:
            return
        if table_id == "instances":
            self._edit_entry(wizard.UPDATE, index,
                             self.server.instances.entries[index].name)
        elif table_id == "backup":
            self._edit_entry(wizard.BACKUP, index,
                             self.server.backups.entries[index].database)
        elif table_id == "maintenance":
            self._edit_job(self.server.maintenance.jobs[index])

    def _edit_entry(self, kind, index, label) -> None:
        """Pick a field of this entry, then change it."""
        if wizard is None:
            self.notify("ownerp_wizard.py is not installed - run ups.",
                        severity="error")
            return
        path = self._path_for(kind)
        lines, data, error = wizard.load_config(path)
        if error:
            self.notify(error, severity="error")
            return
        entries = wizard.entries_of(data, kind)
        if not 0 <= index < len(entries):
            self.action_reload()
            return
        current = entries[index]

        # Scalars only: a list or a mapping has no single line to replace.
        fields = [f for f in wizard.KINDS[kind]["form"]
                  if not isinstance(current.get(f.name), (list, dict))]
        self.push_screen(
            PickField(label, fields, current),
            lambda field: self._change_field(kind, index, field, current))

    def _change_field(self, kind, index, field, current) -> None:
        if field is None:
            return
        self.push_screen(
            EditField(field, current.get(field.name)),
            lambda text: self._write_field(kind, index, field, text))

    def _write_field(self, kind, index, field, text) -> None:
        if text is None:
            return
        try:
            value = wizard.coerce(field.name, text, kind)
        except ValueError:
            self.notify(f"{field.label} expects a number.", severity="error")
            return
        result = wizard.set_field(self._path_for(kind), index, field.name,
                                  value, kind)
        if result.error:
            self.notify(result.error, severity="error")
            return
        if not result.ok:
            errors = [f.message for f in result.findings
                      if f.severity == wizard.validator.ERROR]
            self.notify("Not written: " + (errors[0] if errors else "invalid"),
                        severity="error")
            return
        self.notify(f"{field.label} changed. Backup: "
                    f"{os.path.basename(result.backup)}")
        self.action_reload()

    def _edit_job(self, job) -> None:
        if cron is None:
            self.notify("ownerp_cron.py is not installed - run ups.",
                        severity="error")
            return
        self.push_screen(
            PickJobAction(job),
            lambda action: self._apply_job_action(job, action))

    def _apply_job_action(self, job, action) -> None:
        if action == "toggle":
            self._write_cron(lambda file: cron.set_active(file, job.job_id,
                                                          not job.active))
        elif action == "schedule":
            self.push_screen(
                Reschedule(job),
                lambda schedule: schedule and self._write_cron(
                    lambda file: cron.set_schedule(file, job.job_id, schedule)))

    def _write_cron(self, change) -> None:
        """Load, change, write - through ownerp_cron, which owns the file."""
        try:
            file = cron.load()
            changed, _message = change(file)
            backup = cron.write(file, changed)
        except Exception as exc:                  # CronError, OSError
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Schedule written. Backup: {os.path.basename(backup)}")
        self.action_reload()

    def _path_for(self, kind):
        """The configuration file of this kind, under this console's home.

        Built from self.home rather than taken from KINDS[kind]["path"]: that
        default is resolved at import time against the real $HOME, and --home
        exists so the console can be pointed at a throwaway tree in a test.
        """
        return os.path.join(
            self.home,
            "docker2update.yaml" if kind == wizard.UPDATE
            else "container2backup.yaml")


class PickField(ModalScreen):
    """Which field of this entry. Returns the Field, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label, fields, current):
        super().__init__()
        self.label = label
        self.fields = fields
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.label, classes="dialog-title")
            table = DataTable(id="fields")
            table.cursor_type = "row"
            yield table

    def on_mount(self) -> None:
        table = self.query_one("#fields", DataTable)
        table.add_columns("Field", "Value")
        for field in self.fields:
            value = self.current.get(field.name, "-")
            if wizard.validator.redacted(field.name):
                value = wizard.MASK
            table.add_row(field.label, str(value))
        table.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(DataTable.RowSelected)
    def _selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(self.fields[event.cursor_row])


class PickJobAction(ModalScreen):
    """Switch a job on/off, or reschedule it."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, job):
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.job.job_id, classes="dialog-title")
            yield Label(cron.describe(self.job) if cron else self.job.schedule,
                        classes="dialog-detail")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Switch off" if self.job.active else "Switch on",
                             id="toggle")
                yield Button("Reschedule", variant="primary", id="schedule")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None if event.button.id == "cancel" else event.button.id)


# ==============================================================================
# Tiles
# ==============================================================================

def _tile(title, lines):
    body = "\n".join(lines) if lines else "-"
    return Vertical(Static(title, classes="tile-title"), Static(body),
                    classes="tile")


def _instance_lines(section):
    if not section.known:
        return [section.error]
    if not section.entries:
        return ["none configured"]
    lines = [f"{len(section.entries)} configured"]
    for entry in section.entries[:4]:
        mark = {True: "up", False: "down", None: "?"}[entry.running]
        lines.append(f"{mark:>4}  {entry.name}")
    return lines


def _backup_lines(section):
    if not section.known:
        return [section.error]
    if not section.entries:
        return ["no databases configured"]
    lines = []
    for entry in section.entries[:4]:
        newest = entry.newest
        age = f"{state.human_age(newest.age)} ago" if newest else "no archive"
        lines.append(f"{entry.database:<16.16} {age}")
    if section.disk:
        lines.append(f"target: {section.disk.percent_used} % used")
    return lines


def _maintenance_lines(section):
    if not section.known:
        return [section.error]
    off = [j for j in section.jobs if not j.active]
    lines = [f"{len(section.jobs)} jobs" + (f", {len(off)} off" if off else "")]
    for job in section.jobs[:4]:
        lines.append(f"{'on ' if job.active else 'off'} {job.job_id}")
    return lines


def _system_lines(section):
    if not section.known:
        return [section.error]
    problems = [f for f in section.findings
                if getattr(f.severity, "value", f.severity) in ("WARN", "FAIL")]
    if not problems:
        return [f"all {len(section.findings)} checks pass"]
    return [f"{len(problems)} of {len(section.findings)} need attention"] + \
           [f"  {f.title}" for f in problems[:3]]


# ==============================================================================
# CLI
# ==============================================================================

def preflight(is_tty=None, stdin_tty=None, term=None):
    """Why the console cannot run here, or None.

    Checked before Textual starts, so a refusal is a sentence rather than a
    traceback out of a half-built screen - and it names the commands that do
    work, because being told what does not work is only half an answer.
    """
    is_tty = sys.stdout.isatty() if is_tty is None else is_tty
    stdin_tty = sys.stdin.isatty() if stdin_tty is None else stdin_tty
    term = os.environ.get("TERM", "") if term is None else term
    if not is_tty or not stdin_tty:
        return ("The console needs a terminal. Use `dostat` for the same "
                "facts as text - it works in a pipe, a mail and a cron job.")
    if term in ("", "dumb"):
        return (f"TERM={term or 'unset'} cannot draw the console. "
                f"Use `dostat` instead.")
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print(f"ownerp_console.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__ or "ownerp_console.py - the ownERP console")
        print("  --version    print the version\n"
              "  --home PATH  where the configurations live")
        return 0

    home = None
    if "--home" in argv:
        try:
            home = argv[argv.index("--home") + 1]
        except IndexError:
            print("--home needs a path", file=sys.stderr)
            return 2

    reason = preflight()
    if reason:
        print(reason, file=sys.stderr)
        return 2

    Console(home=home).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
