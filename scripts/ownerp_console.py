#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_console.py
# Description:      The ownERP console: server state, and the configuration
#                   editing that used to mean hand-writing YAML.
# Version:          1.2.0
# Date:             21.08.2026
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

SCRIPT_VERSION = "1.2.0"
SCRIPT_DATE = "21.08.2026"

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

FALLBACKS = """\
Everything the console does also works without it:

    dostat     the state of this server, as text
    wiz        add or change an entry (asks which configuration)
    docron     the maintenance schedule
    doval      check both configurations
"""


def no_textual_message(uv_found=None):
    """Why the console cannot start, and what actually fixes it on this server.

    It used to say `pip install --user textual`, which is wrong twice over: on
    Debian 12 and later that refuses with an externally-managed-environment
    error, and installing it by hand is not how anything else on an ownERP
    server arrives. `ups` installs it - naming anything else sends an operator
    down a path this project does not maintain.

    The cause is split out because the two are not the same problem. Missing uv
    is fixed by an update; an unreachable PyPI is not fixed by anything the
    operator types here, and saying so is more useful than a command that will
    fail again.
    """
    import shutil
    if uv_found is None:
        uv_found = shutil.which("uv") is not None
    cause = ("Textual could not be fetched - this server has no route to PyPI, "
             "or a proxy sits in front of it."
             if uv_found else
             "uv is missing, and that is what the console installs Textual with.")
    return (f"The console needs Textual, and it is not available.\n"
            f"{cause}\n\n"
            f"    ups        installs it - that is where this belongs\n\n"
            f"{FALLBACKS}")


def _reexec_through_uv():
    """Restart through `uv run --with textual`, once.

    uv is a prerequisite on every ownERP server, and it caches the resolved
    environment - the network is touched on the first start and not again. The
    guard variable is what keeps a failure from looping: if the re-executed
    process still cannot import Textual, it prints the message and stops.

    A non-zero exit from uv itself falls through to the message rather than
    exiting on it. uv's own error explains what it could not download; it does
    not say that `ups` is what installs this, or that dostat covers most of
    what the operator came for.
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
        completed = subprocess.run(uv_command(sys.argv[1:], uv),
                                   env=environment, check=False)
    except OSError:
        return False
    if completed.returncode == ALREADY_REPORTED:
        # The child is this same script and has already printed the message.
        # Printing it a second time from here says nothing new and reads like
        # two separate failures.
        sys.exit(ALREADY_REPORTED)
    if completed.returncode != 0:
        return False
    sys.exit(completed.returncode)


# Our own "I have already explained this" exit code, distinct from uv's.
ALREADY_REPORTED = 2


def uv_command(argv=(), uv="uv"):
    """The exact command that starts the console through uv.

    One builder, because the warm-up in getScripts.py must run the command the
    console actually runs. It did not, and the difference was invisible: the
    warm-up passed `python3`, this passed `sys.executable`.

    That single word is the whole bug. `uv run --with textual python3` lets uv
    resolve the interpreter inside the environment it just built; handing it
    /usr/bin/python3 starts the system interpreter instead, which cannot see
    those packages - a virtualenv takes effect through its own binary, not
    through PATH. So the warm-up reported success while every real start
    failed, on the same machine, minutes apart.
    """
    command = [uv, "run", "--quiet", "--no-project"]
    for spec in DEPENDENCIES:
        command += ["--with", spec]
    return command + ["python3", os.path.abspath(__file__)] + list(argv)


try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import (Button, DataTable, Footer, Header, Input,
                                 Label, ListItem, ListView, Static, Switch,
                                 TabbedContent, TabPane)
except ImportError:                              # pragma: no cover - by design
    if __name__ == "__main__" and _reexec_through_uv() is False:
        print(no_textual_message(), file=sys.stderr)
        sys.exit(ALREADY_REPORTED)
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
mute = _sibling("ownerp_mute.py", "ownerp_mute")


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


# The menu box is 32 wide: 2 for the border, 2 for padding, 2 for the list's
# own padding. Anything longer is clipped, not wrapped.
MENU_LABEL_WIDTH = 26


class ActionMenu(ModalScreen):
    """What to do with the selected row. Returns an action name, or None.

    ctop's menu: a small box at the top left, one letter per action, the
    keystroke and the list entry doing the same thing so neither hand nor eye
    has to switch. It decides nothing — it names what the caller offered and
    hands one of those names back.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title, actions):
        """actions: a list of (key, label, name)."""
        super().__init__()
        self.title_text = title
        self.actions = list(actions)

    def compose(self) -> ComposeResult:
        with Vertical(classes="menu"):
            yield Label(self.title_text, classes="menu-title")
            # markup=False, or the whole point of the menu disappears: "[e]"
            # is valid Rich markup for a style tag, so a Label renders it as
            # nothing at all and every line loses its key.
            yield ListView(
                *[ListItem(Label(f"[{key}] {label}", markup=False),
                           id=f"act-{name}")
                  for key, label, name in self.actions],
                id="actions")

    def on_mount(self) -> None:
        self.query_one("#actions", ListView).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        """The letter shortcuts. The list handles arrows and Enter itself."""
        for key, _label, name in self.actions:
            if event.key == key:
                event.stop()
                self.dismiss(None if name == "cancel" else name)
                return

    @on(ListView.Selected)
    def _selected(self, event: ListView.Selected) -> None:
        name = (event.item.id or "").removeprefix("act-")
        self.dismiss(None if name == "cancel" else name)


class EntryForm(ModalScreen):
    """A whole entry as a form. Returns {field: value} of what changed, or None.

    This replaces a pick-a-field/enter-a-value pair of modals, and the reason
    it may is ownerp_wizard.set_fields(): the whole set is validated once and
    the file is replaced once, so a form cannot half-apply. Without that this
    would be several writes wearing one dialog's clothes — which is exactly
    what the two modals were avoiding.

    A boolean is a Switch, not a field where someone types "true". The help
    text of the focused field is shown at the bottom rather than beside every
    row: the prompt wizard printed it per question, and a form that dropped it
    would be prettier and less informative.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title, kind, fields, current, creating=False):
        super().__init__()
        self.title_text = title
        self.kind = kind
        self.fields = list(fields)
        self.current = dict(current or {})
        self.creating = creating

    def compose(self) -> ComposeResult:
        with Vertical(classes="form"):
            yield Label(self.title_text, classes="dialog-title")
            with VerticalScroll(id="form-rows"):
                for field in self.fields:
                    yield Label(field.label, classes="form-label")
                    yield self._widget_for(field)
            yield Label("", id="form-help", classes="dialog-detail")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def _widget_for(self, field):
        value = self.current.get(field.name)
        if _is_secret(field.name):
            # Never render the stored password, not even masked into a value
            # that could be written straight back. Empty means "leave it".
            return Input(value="", password=True,
                         placeholder="unchanged" if not self.creating else "",
                         id=f"f-{field.name}", classes="form-input")
        if _is_boolean(self.kind, field.name):
            return Switch(value=bool(value), id=f"f-{field.name}",
                          classes="form-switch")
        return Input(value="" if value is None else str(value),
                     id=f"f-{field.name}", classes="form-input")

    def on_mount(self) -> None:
        first = self.query(".form-input, .form-switch")
        if first:
            first[0].focus()

    def on_descendant_focus(self, event) -> None:
        """Show the focused field's help — the prompt wizard's one advantage."""
        name = (getattr(event.widget, "id", "") or "").removeprefix("f-")
        for field in self.fields:
            if field.name == name:
                self.query_one("#form-help", Label).update(field.help or "")
                return

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        changes, bad = {}, None
        for field in self.fields:
            widget = self.query_one(f"#f-{field.name}")
            if isinstance(widget, Switch):
                value = widget.value
                if self.creating or value != bool(self.current.get(field.name)):
                    changes[field.name] = value
                continue

            text = widget.value
            if _is_secret(field.name):
                # An untouched password field means "unchanged", never "".
                if text:
                    changes[field.name] = text
                continue
            if not self.creating and text == _as_text(self.current.get(field.name)):
                continue
            if not text.strip() and not self.creating:
                bad = bad or f"{field.label} cannot be emptied here."
                continue
            try:
                changes[field.name] = wizard.coerce(field.name, text, self.kind)
            except ValueError:
                bad = bad or f"{field.label} expects a number."

        if bad:
            self.notify(bad, severity="error")
            return
        if not changes and not self.creating:
            self.dismiss(None)
            return
        self.dismiss(changes)


def _is_secret(name):
    return wizard is not None and wizard.validator.redacted(name)


def _is_boolean(kind, name):
    """Whether the schema types this field as a boolean.

    Read from the validator's schema rather than from the current value: a
    field that is absent has no value to infer a type from, and rendering it
    as a text box is how "true" ends up quoted in the file.
    """
    if wizard is None:
        return False
    rule = wizard.KINDS[kind]["fields"]().get(name, {})
    return rule.get("type") is bool


def _as_text(value):
    return "" if value is None else str(value)


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


class MuteReason(ModalScreen):
    """Why a finding does not apply on this host. Required, not optional.

    An entry nobody can justify a year later gets removed rather than
    understood, which brings the message back on a host that decided against it.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, finding):
        super().__init__()
        self.finding = finding

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Mute {self.finding.title}", classes="dialog-title")
            yield Label("It keeps running and keeps its line in the full "
                        "report — it stops counting.", classes="dialog-detail")
            yield Input(placeholder="why it does not apply here", id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Mute", variant="primary", id="save")
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
        if not text:
            self.notify("A reason is required.", severity="error")
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

    /* The action menu sits top left, over the table it acts on - ctop's
       placement, and the reason it is not centred: the row it belongs to
       must stay visible while the menu is open. */
    ActionMenu { align: left top; }
    .menu {
        width: 32; height: auto; margin: 3 0 0 2; padding: 0 1;
        background: $panel; border: round $accent;
    }
    .menu-title { text-style: bold; padding: 0 0 1 0; }
    .menu ListView { height: auto; background: $panel; }
    .menu ListItem { background: $panel; padding: 0 1; }

    .form {
        width: 76; height: 80%; padding: 1 2;
        background: $panel; border: thick $primary;
    }
    #form-rows { height: 1fr; }
    /* Two columns: a fixed label gutter wide enough for the longest label in
       either form, and the input taking the rest. */
    #form-rows { layout: grid; grid-size: 2; grid-columns: 34 1fr;
                 grid-rows: 3; grid-gutter: 0 1; }
    .form-label { padding: 1 0 0 0; }
    .form-switch { height: 3; }
    #tiles { grid-size: 2; grid-gutter: 1 2; padding: 1 2; height: auto; }
    .tile { border: round $primary; padding: 0 1; height: auto; min-height: 7; }
    .tile-title { text-style: bold; }
    .unknown { color: $warning; padding: 1 2; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("n", "new_entry", "New"),
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
        self._rows["system"] = {}
        section = self.server.health
        if not section.known:
            table.add_row("?", section.error, "")
            return
        for index, finding in enumerate(section.findings):
            severity = getattr(finding.severity, "value", finding.severity)
            key = table.add_row(
                {"OK": "ok", "WARN": "!", "FAIL": "XX", "MUTED": "off"}.get(severity, "-"),
                finding.title,
                f"{finding.detail} ({finding.note})" if finding.note else finding.detail)
            self._rows["system"][key] = index

    # -- editing ---------------------------------------------------------
    #
    # One route for every change: select a row, get the menu of what this tab
    # can do with it, and land either in the form or in a single toggle. The
    # menu is what the row offers, not what the console decides.

    # Labels are kept inside MENU_LABEL_WIDTH: the box does not grow to fit,
    # it clips, and a clipped entry reads as a different setting than the one
    # it toggles ("database only, no filest").
    ACTIONS = {
        "instances": (("e", "edit entry", "edit"),
                      ("n", "new instance", "new"),
                      ("a", "toggle updates on/off", "toggle-active"),
                      ("c", "cancel", "cancel")),
        "backup": (("e", "edit entry", "edit"),
                   ("n", "new database", "new"),
                   ("s", "toggle SQL-only backup", "toggle-sql"),
                   ("c", "cancel", "cancel")),
        "maintenance": (("e", "change schedule", "schedule"),
                        ("t", "switch job on/off", "toggle"),
                        ("c", "cancel", "cancel")),
        "system": (("m", "mute on this host", "mute"),
                   ("u", "unmute", "unmute"),
                   ("c", "cancel", "cancel")),
    }

    KINDS_BY_TABLE = {"instances": "update", "backup": "backup"}

    # The one field each toggle flips, and the label the notification uses.
    TOGGLES = {
        "toggle-active": ("active", "Take part in updates"),
        "toggle-sql": ("only_sql_dump", "Database only, no filestore"),
    }

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        index = self._rows.get(table_id, {}).get(event.row_key)
        if index is None or table_id not in self.ACTIONS:
            return
        self.push_screen(
            ActionMenu(self._row_title(table_id, index),
                       self.ACTIONS[table_id]),
            lambda action: self._act(table_id, index, action))

    def _row_title(self, table_id, index) -> str:
        if table_id == "instances":
            return self.server.instances.entries[index].name
        if table_id == "backup":
            return self.server.backups.entries[index].database
        if table_id == "system":
            return self.server.health.findings[index].title
        return self.server.maintenance.jobs[index].job_id

    def _act(self, table_id, index, action) -> None:
        if action is None:
            return
        if table_id == "maintenance":
            self._act_on_job(self.server.maintenance.jobs[index], action)
            return
        if table_id == "system":
            self._act_on_finding(self.server.health.findings[index], action)
            return
        if not self._have_wizard():
            return
        kind = self.KINDS_BY_TABLE[table_id]
        if action == "edit":
            self._open_form(kind, index)
        elif action == "new":
            self._new_entry(kind)
        elif action in self.TOGGLES:
            self._toggle(kind, index, *self.TOGGLES[action])

    def action_new_entry(self) -> None:
        """New entry for the visible tab, without selecting a row first.

        An empty table has no row to select, which is exactly the state a new
        server is in.
        """
        table_id = self.query_one("#tabs", TabbedContent).active.removeprefix(
            "tab-")
        if table_id not in self.KINDS_BY_TABLE:
            return
        if self._have_wizard():
            self._new_entry(self.KINDS_BY_TABLE[table_id])

    def _have_wizard(self) -> bool:
        if wizard is None:
            self.notify("ownerp_wizard.py is not installed - run ups.",
                        severity="error")
            return False
        return True

    def _load(self, kind):
        """(entries, error-shown). The console never parses a file itself."""
        _lines, data, error = wizard.load_config(self._path_for(kind))
        if error:
            self.notify(error, severity="error")
            return None
        return wizard.entries_of(data, kind)

    def _open_form(self, kind, index) -> None:
        entries = self._load(kind)
        if entries is None:
            return
        if not 0 <= index < len(entries):
            self.action_reload()
            return
        current = entries[index]

        # Scalars only: a list or a mapping has no single line to replace.
        fields = [f for f in wizard.KINDS[kind]["form"]
                  if not isinstance(current.get(f.name), (list, dict))]
        label = current.get(wizard.KINDS[kind]["unique"][0], "entry")
        self.push_screen(
            EntryForm(f"{wizard.KINDS[kind]['label']} · {label}",
                      kind, fields, current),
            lambda changes: self._save_changes(kind, index, changes))

    def _save_changes(self, kind, index, changes) -> None:
        if not changes:
            return
        result = wizard.set_fields(self._path_for(kind), index, changes, kind)
        self._report(result, f"{len(changes)} field(s) changed")

    def _toggle(self, kind, index, field, label) -> None:
        entries = self._load(kind)
        if entries is None or not 0 <= index < len(entries):
            return
        new_value = not bool(entries[index].get(field))
        result = wizard.set_field(self._path_for(kind), index, field,
                                  new_value, kind)
        self._report(result, f"{label}: {'yes' if new_value else 'no'}")

    def _new_entry(self, kind) -> None:
        entries = self._load(kind)
        if entries is None:
            return
        self.push_screen(
            EntryForm(f"New {wizard.KINDS[kind]['label']}", kind,
                      list(wizard.KINDS[kind]["form"]),
                      _suggested(kind, entries), creating=True),
            lambda values: self._create(kind, entries, values))

    def _create(self, kind, entries, values) -> None:
        if not values:
            return
        entry = _complete(kind, entries, values)
        missing = [f.label for f in wizard.KINDS[kind]["form"]
                   if wizard.validator.is_empty(entry.get(f.name))
                   and f.name in wizard.KINDS[kind]["unique"]]
        if missing:
            self.notify(f"{missing[0]} is required.", severity="error")
            return
        self.push_screen(
            Confirm(f"Add {entry.get(wizard.KINDS[kind]['unique'][0])}?",
                    "\n".join(wizard.summary_lines(
                        entry, wizard.KINDS[kind]["form"]))),
            lambda yes: yes and self._write_new(kind, entry))

    def _write_new(self, kind, entry) -> None:
        result = wizard.add_entry(self._path_for(kind), entry, kind)
        self._report(result, f"{entry.get(wizard.KINDS[kind]['unique'][0])} added")

    def _report(self, result, success) -> None:
        """One place turns a WriteResult into a message and a reload."""
        if result.error:
            self.notify(result.error, severity="error")
            return
        if not result.ok:
            errors = [f.message for f in result.findings
                      if f.severity == wizard.validator.ERROR]
            self.notify("Not written: " + (errors[0] if errors else "invalid"),
                        severity="error")
            return
        self.notify(f"{success}. Backup: {os.path.basename(result.backup)}")
        self.action_reload()

    def _act_on_job(self, job, action) -> None:
        if cron is None:
            self.notify("ownerp_cron.py is not installed - run ups.",
                        severity="error")
            return
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

    def _act_on_finding(self, finding, action) -> None:
        if mute is None:
            self.notify("ownerp_mute.py is not installed - run ups.",
                        severity="error")
            return
        if action == "mute":
            self.push_screen(
                MuteReason(finding),
                lambda reason: reason and self._write_mute(
                    lambda: mute.mute(self.home, finding.check_id, reason)))
        elif action == "unmute":
            self._write_mute(lambda: mute.unmute(self.home, finding.check_id))

    def _write_mute(self, change) -> None:
        """Through ownerp_mute, which owns the file. The console writes nothing."""
        try:
            change()
        except Exception as exc:                  # MuteError, OSError
            self.notify(str(exc), severity="error")
            return
        self.notify("Mute list updated.")
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


# ==============================================================================
# Suggestions for a new entry
# ==============================================================================
#
# The prompt wizard asks field by field, so by the time it reaches the build
# folder it knows the container name and can suggest a path from it. A form
# shows every field at once and therefore cannot: at open time the name is
# still blank. Hence two passes — suggest what can be known up front, and fill
# whatever the operator left empty once the name exists.

def _suggest_one(field, entries, entry):
    """One suggestion, or None. A helper must never be the thing that fails."""
    if field.suggest is None:
        return None
    try:
        return field.suggest(entries, entry)
    except Exception:
        return None


def _suggested(kind, entries):
    """Pre-fill for a new entry: everything that does not need the name yet."""
    entry = {}
    for field in wizard.KINDS[kind]["form"]:
        value = _suggest_one(field, entries, entry)
        if value is not None and not wizard.validator.is_empty(value):
            entry[field.name] = value
    return entry


def _complete(kind, entries, values):
    """The operator's values, plus a suggestion for each one left blank.

    Run after the form closes, when container_name is finally known — this is
    what turns an empty build folder into $HOME/docker-builds/<name>/ the way
    the prompt wizard does.
    """
    entry = {name: value for name, value in values.items()
             if not wizard.validator.is_empty(value)}
    for field in wizard.KINDS[kind]["form"]:
        if field.name in entry:
            continue
        value = _suggest_one(field, entries, entry)
        if value is not None and not wizard.validator.is_empty(value):
            entry[field.name] = value
    return entry


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
              "  --check      report whether the console can start\n"
              "  --home PATH  where the configurations live")
        return 0
    if "--check" in argv:
        # Reaching this line IS the check: the import at the top of this file
        # succeeded, in this process, having come through whatever re-exec was
        # needed. That is why ups runs the console itself rather than a
        # rebuilt approximation of its command - the approximation passed while
        # the real thing failed, and nothing could see the difference.
        print(f"console: ok (textual available, {SCRIPT_VERSION})")
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
