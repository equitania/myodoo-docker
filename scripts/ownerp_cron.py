#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_cron.py
# Description:      Overview and guided editing of the myodoo maintenance cron.
# Version:          1.0.1
# Date:             13.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   /etc/cron.d/myodoo-maintenance runs the jobs an ownERP server depends on —
#   backup, cert renewal, DNS guard, log cleanup, readiness. Until now the only
#   way to see WHEN they run was to read the file, and the only way to change a
#   time was to edit it by hand: an unvalidated write to a file where a typo is
#   silent. cron does not complain about a malformed line, it just never runs
#   the job, and nobody notices until a restore is needed.
#
#   Two consumers, one implementation:
#     * getScripts.py (`ups`) prints --brief after the install summary. Purely
#       informational and non-interactive, because ups also runs from scripts
#       and from cron itself, where there is no terminal to prompt on.
#     * ownerp_console.py edits through this module's API, so the write
#       path exists exactly once.
#
# Write safety (mirrors ownerp_wizard.py, deliberately):
#   timestamped backup -> build in memory -> temp file in the SAME directory ->
#   re-parse and validate that file -> os.replace(). On any error the temp file
#   is removed and the original is left byte-identical. cron.d also demands mode
#   0644 and root ownership, which the temp file gets BEFORE the rename — a
#   group-writable cron.d file is ignored by cron without a word.
#
# Local customisation vs. drift:
#   Editing a schedule makes the installed file differ from the repository
#   template, which server-readiness.py reports as drift. That is right for an
#   accidental difference and wrong for a deliberate one, so an edit writes an
#   EDIT_MARKER line into the header. server-readiness.py v1.4.0 reads it and
#   reports "customised locally" instead of "schedule differs".
#
#   Re-running setup-maintenance-cron.sh restores the template and discards the
#   customisation. That is its job; this module says so before it writes.
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

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SCRIPT_VERSION = "1.0.2"
SCRIPT_DATE = "13.08.2026"

CRON_PATH = "/etc/cron.d/myodoo-maintenance"

# A job switched off through this tool keeps its line, prefixed with an explicit
# marker. Plain "#" would be indistinguishable from the file's documentation
# comments, and deleting the line would lose the schedule the operator may want
# back tomorrow.
DISABLED_PREFIX = "#OWNERP-DISABLED# "

# Header line recording that this file was edited locally. See the module docstring.
EDIT_MARKER = "# ownerp-cron-edit:"

# Environment assignments (MAILTO=, PATH=) are not jobs.
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*\s*=")

# Commands that start with one of these run something else; the something else
# is the job's name. `/usr/bin/python3 /root/odoo_build_cache.py gc` is the
# build-cache job, not the "python3 job".
INTERPRETERS = {"python3", "python", "python3.11", "python3.12", "python3.13",
                "bash", "sh", "dash", "zsh", "perl", "env"}

# min, hour, day-of-month, month, day-of-week. dow 7 == Sunday, as cron allows.
FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")

# @reboot has no schedule to validate and no next run to predict; it is accepted
# but never rewritten by this tool.
SHORTCUTS = {"@reboot", "@yearly", "@annually", "@monthly", "@weekly",
             "@daily", "@midnight", "@hourly"}

WEEKDAYS = {0: "Sundays", 1: "Mondays", 2: "Tuesdays", 3: "Wednesdays",
            4: "Thursdays", 5: "Fridays", 6: "Saturdays", 7: "Sundays"}


class CronError(Exception):
    """Raised for anything that must stop a write before it happens."""


@dataclass
class CronJob:
    """One executable line of the cron file, active or switched off."""

    line_no: int          # 0-based index into the file's line list
    active: bool
    schedule: str         # "0 2 * * *" or an @shortcut
    user: str
    command: str
    suffix: int = 0       # >0 when several jobs run the same script
    # Only a mutated job's line is re-rendered. Rewriting every line would
    # collapse the template's column alignment on jobs nobody touched, and
    # would leave _regression() nothing to compare — a guard that inspects
    # lines it rewrote itself proves nothing.
    dirty: bool = False

    @property
    def script(self) -> str:
        """Basename of the script the job runs.

        The command is `/root/container2backup.py </dev/null >> /var/log/...`,
        and the operator recognises the script, not the redirects. One entry
        runs `/usr/bin/python3 /root/odoo_build_cache.py gc`, so the first
        absolute path is not always the answer — an interpreter is a detail of
        how the job starts, never its identity.
        """
        tokens = self.command.split()
        fallback = None
        for token in tokens:
            if not token.startswith("/") or token.startswith("/dev"):
                continue
            name = os.path.basename(token)
            if name in INTERPRETERS:
                fallback = fallback or name
                continue
            return name
        return fallback or (tokens[0] if tokens else "?")

    @property
    def job_id(self) -> str:
        """Stable handle used on the command line and in the console.

        The backup runs twice a day from two lines, so the script name alone is
        ambiguous; the duplicates get :1, :2 in file order.
        """
        return f"{self.script}:{self.suffix}" if self.suffix else self.script

    @property
    def log_path(self) -> Optional[str]:
        """Redirect target of the job, if it has one.

        server-readiness.py deliberately has no redirect (it mails on drift
        instead), so "no log" is a designed state, not a defect.
        """
        match = re.search(r">>?\s*(/\S+\.log)", self.command)
        return match.group(1) if match else None


@dataclass
class CronFile:
    """Parsed cron file: the raw lines plus the jobs that point into them."""

    path: str
    lines: List[str] = field(default_factory=list)
    jobs: List[CronJob] = field(default_factory=list)

    def job(self, job_id: str) -> CronJob:
        for candidate in self.jobs:
            if candidate.job_id == job_id:
                return candidate
        # A bare script name is unambiguous whenever it occurs once.
        matches = [c for c in self.jobs if c.script == job_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CronError(
                f"'{job_id}' is ambiguous — {len(matches)} jobs run it. Use one of: "
                + ", ".join(c.job_id for c in matches))
        raise CronError(f"unknown job '{job_id}'. Known: "
                        + ", ".join(c.job_id for c in self.jobs))

    @property
    def customised(self) -> bool:
        return any(line.startswith(EDIT_MARKER) for line in self.lines)


# ==============================================================================
# Parsing and rendering
# ==============================================================================

def parse_text(text: str, path: str = CRON_PATH) -> CronFile:
    """Parse a cron.d file into lines plus jobs.

    Every line is kept verbatim; jobs only record where they live. That is what
    lets a rewrite touch one line and leave the file's comments, ordering and
    trailing whitespace exactly as the operator (or the repo) wrote them.
    """
    lines = text.splitlines()
    jobs: List[CronJob] = []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        active = True
        if stripped.startswith(DISABLED_PREFIX.strip()):
            active = False
            stripped = stripped[len(DISABLED_PREFIX.strip()):].strip()
        elif stripped.startswith("#") or not stripped:
            continue
        if _ENV_RE.match(stripped):
            continue
        parsed = _split_job(stripped)
        if parsed is None:
            continue
        schedule, user, command = parsed
        jobs.append(CronJob(index, active, schedule, user, command))

    # Disambiguate scripts that appear more than once (the backup runs twice).
    seen = {}
    for job in jobs:
        seen.setdefault(job.script, []).append(job)
    for script_jobs in seen.values():
        if len(script_jobs) > 1:
            for number, job in enumerate(script_jobs, start=1):
                job.suffix = number

    return CronFile(path=path, lines=lines, jobs=jobs)


def _split_job(line: str) -> Optional[Tuple[str, str, str]]:
    """Split a cron.d line into (schedule, user, command), or None if it is not one."""
    parts = line.split()
    if not parts:
        return None
    if parts[0] in SHORTCUTS:
        if len(parts) < 3:
            return None
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) < 7:
        return None
    return " ".join(parts[:5]), parts[5], " ".join(parts[6:])


def render_job(job: CronJob) -> str:
    """Render a job back to a cron.d line, honouring its active flag."""
    line = f"{job.schedule} {job.user} {job.command}"
    return line if job.active else DISABLED_PREFIX + line


def render(cron: CronFile) -> str:
    """Rebuild the file text, rewriting only the lines of mutated jobs.

    Everything else — comments, blank lines, the template's column alignment,
    even trailing spaces — is handed back exactly as it came in.
    """
    lines = list(cron.lines)
    for job in cron.jobs:
        if job.dirty:
            lines[job.line_no] = render_job(job)
    return "\n".join(lines) + "\n"


# ==============================================================================
# Validation
# ==============================================================================

def validate_schedule(schedule: str) -> Optional[str]:
    """Return an error message for an invalid schedule, or None if it is fine.

    Deliberately strict about ranges: cron accepts `0 25 * * *` at write time
    and then simply never fires it. A validator that only checks the field count
    would let exactly the mistake through that this tool exists to prevent.
    """
    schedule = schedule.strip()
    if schedule in SHORTCUTS:
        return None
    if schedule.startswith("@"):
        return f"unknown cron shortcut '{schedule}'"

    fields = schedule.split()
    if len(fields) != 5:
        return (f"a schedule needs 5 fields (minute hour day month weekday), "
                f"got {len(fields)}: '{schedule}'")

    for value, (low, high), name in zip(fields, FIELD_RANGES, FIELD_NAMES):
        error = _validate_field(value, low, high, name)
        if error:
            return error
    return None


def _validate_field(value: str, low: int, high: int, name: str) -> Optional[str]:
    for item in value.split(","):
        if not item:
            return f"{name}: empty list element in '{value}'"
        step_parts = item.split("/")
        if len(step_parts) > 2:
            return f"{name}: more than one step in '{item}'"
        if len(step_parts) == 2:
            if not step_parts[1].isdigit() or int(step_parts[1]) == 0:
                return f"{name}: step must be a positive number in '{item}'"
        base = step_parts[0]
        if base == "*":
            continue
        bounds = base.split("-")
        if len(bounds) > 2:
            return f"{name}: malformed range '{base}'"
        numbers = []
        for bound in bounds:
            if not bound.isdigit():
                return f"{name}: '{bound}' is not a number in '{item}'"
            numbers.append(int(bound))
        for number in numbers:
            if not low <= number <= high:
                return f"{name}: {number} is outside {low}-{high}"
        if len(numbers) == 2 and numbers[0] > numbers[1]:
            return f"{name}: range '{base}' runs backwards"
    return None


def _regression(before: CronFile, after: CronFile, expect: CronJob) -> Optional[str]:
    """Refuse a write that changed anything beyond the one intended job.

    The same guard ownerp_wizard.py uses: a rewrite is allowed to alter exactly
    what was asked for, and the way to prove it is to compare the parse of the
    new file against the parse of the old one, job by job.
    """
    if len(before.jobs) != len(after.jobs):
        return (f"job count changed ({len(before.jobs)} -> {len(after.jobs)}) — "
                "refusing the write")
    for old, new in zip(before.jobs, after.jobs):
        if old.job_id == expect.job_id:
            continue
        if (old.schedule, old.user, old.command, old.active) != \
           (new.schedule, new.user, new.command, new.active):
            return f"unrelated job '{old.job_id}' would change — refusing the write"
    return None


# ==============================================================================
# Reading the live state
# ==============================================================================

def load(path: str = CRON_PATH) -> CronFile:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return parse_text(handle.read(), path=path)
    except FileNotFoundError:
        raise CronError(f"{path} not found — run setup-maintenance-cron.sh first")
    except OSError as exc:
        raise CronError(f"cannot read {path}: {exc}")


def last_run(job: CronJob) -> Optional[float]:
    """Epoch time of the job's last log write, or None.

    The log's mtime is a proxy, not a receipt: it says when the job last wrote
    output, which for these jobs is every run. A job whose log is missing has
    either never run or never had a redirect — describe(), not this function,
    tells those two apart.
    """
    path = job.log_path
    if not path:
        return None
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def humanise(schedule: str) -> str:
    """Turn a cron schedule into something readable, or hand it back unchanged.

    Only the shapes this file actually uses are translated. A schedule that is
    not recognised is shown raw rather than approximated — a wrong-but-friendly
    "daily" on a job that runs every 15 minutes is worse than no translation.
    """
    if schedule in SHORTCUTS:
        return schedule.lstrip("@")
    fields = schedule.split()
    if len(fields) != 5:
        return schedule
    minute, hour, dom, month, dow = fields
    if not (minute.isdigit() and hour.isdigit()):
        return schedule
    clock = f"{int(hour):02d}:{int(minute):02d}"
    if (dom, month, dow) == ("*", "*", "*"):
        return f"daily {clock}"
    if dom == "*" and month == "*" and dow.isdigit():
        return f"{WEEKDAYS[int(dow)]} {clock}"
    return schedule


def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds / 60)}m ago"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h ago"
    return f"{int(seconds / 86400)}d ago"


def describe(job: CronJob) -> str:
    """Human phrase for a job's last run."""
    if not job.log_path:
        return "no log"
    stamp = last_run(job)
    if stamp is None:
        return "never"
    return _age(time.time() - stamp)


# ==============================================================================
# Writing
# ==============================================================================

def _backup(path: str) -> str:
    target = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(path, target)
    return target


def _stamp_marker(cron: CronFile) -> None:
    """Record in the file that it carries deliberate local changes.

    Placed after the leading comment block so it reads as part of the header.
    Rewritten rather than appended, so repeated edits leave one marker.
    """
    note = (f"{EDIT_MARKER} locally customised on {time.strftime('%d.%m.%Y')} "
            f"via ownerp_cron.py — setup-maintenance-cron.sh would reset this")
    for index, line in enumerate(cron.lines):
        if line.startswith(EDIT_MARKER):
            cron.lines[index] = note
            return
    insert_at = 0
    for index, line in enumerate(cron.lines):
        if line.startswith("#"):
            insert_at = index + 1
        elif line.strip():
            break
    cron.lines.insert(insert_at, note)
    for job in cron.jobs:
        if job.line_no >= insert_at:
            job.line_no += 1


def write(cron: CronFile, changed: CronJob) -> str:
    """Persist the file. Returns the backup path.

    Order matters and is the whole point: backup first, then a temp file in the
    same directory (so the rename is atomic and cannot cross a filesystem), then
    validate what was actually written by re-parsing it, and only then replace.
    A failure at any step removes the temp file and leaves the original as it was.
    """
    error = validate_schedule(changed.schedule)
    if error:
        raise CronError(error)

    backup = _backup(cron.path)
    _stamp_marker(cron)
    text = render(cron)

    temp = f"{cron.path}.tmp_{os.getpid()}"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
        # cron silently ignores a cron.d file that is group- or world-writable.
        os.chmod(temp, 0o644)

        verify = parse_text(text, path=cron.path)
        for job in verify.jobs:
            if job.active:
                problem = validate_schedule(job.schedule)
                if problem:
                    raise CronError(f"{job.job_id}: {problem}")
        original = load(cron.path)
        problem = _regression(original, verify, changed)
        if problem:
            raise CronError(problem)

        os.replace(temp, cron.path)
    except Exception:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return backup


def set_schedule(cron: CronFile, job_id: str, schedule: str) -> Tuple[CronJob, str]:
    job = cron.job(job_id)
    error = validate_schedule(schedule)
    if error:
        raise CronError(error)
    job.schedule = schedule.strip()
    job.dirty = True
    return job, write(cron, job)


def set_active(cron: CronFile, job_id: str, active: bool) -> Tuple[CronJob, str]:
    job = cron.job(job_id)
    job.active = active
    job.dirty = True
    return job, write(cron, job)


# ==============================================================================
# Report
# ==============================================================================

def _palette(stream) -> dict:
    if not hasattr(stream, "isatty") or not stream.isatty():
        return {k: "" for k in ("green", "yellow", "dim", "reset")}
    return {"green": "\033[0;32m", "yellow": "\033[1;33m",
            "dim": "\033[2m", "reset": "\033[0m"}


def print_report(cron: CronFile, brief: bool = False, stream=None) -> None:
    """Print the overview. `brief` is what `ups` shows after the install summary."""
    stream = stream or sys.stdout
    colour = _palette(stream)
    width = 60 if brief else 72

    print("", file=stream)
    print("=" * width, file=stream)
    print("Maintenance cron", file=stream)
    print("=" * width, file=stream)

    if not cron.jobs:
        print("  no jobs configured — run setup-maintenance-cron.sh", file=stream)
        print("=" * width, file=stream)
        return

    name_width = max(len(job.job_id) for job in cron.jobs)
    sched_width = max(len(humanise(job.schedule)) for job in cron.jobs)
    inactive = 0
    for job in cron.jobs:
        if job.active:
            mark, tint = "✓", colour["green"]
        else:
            mark, tint = "•", colour["yellow"]
            inactive += 1
        line = (f"  {tint}{mark}{colour['reset']} "
                f"{job.job_id:<{name_width}}  "
                f"{humanise(job.schedule):<{sched_width}}  "
                f"{colour['dim']}{describe(job)}{colour['reset']}")
        print(line, file=stream)

    print("-" * width, file=stream)
    summary = f"  {len(cron.jobs) - inactive} active"
    if inactive:
        summary += f" · {inactive} switched off"
    if cron.customised:
        summary += " · locally customised"
    print(summary, file=stream)
    # The hint belongs in BOTH modes. `ups` prints the brief form, and that is
    # the only place most operators ever see this table — a schedule they
    # cannot act on is a schedule they will change by hand in an editor, which
    # is the unvalidated write this tool exists to replace.
    if brief:
        print("  Edit: konsole  ·  docron --help", file=stream)
    else:
        print("  Edit with 'konsole', or:", file=stream)
        print("    docron --set <job> --schedule '0 2 * * *'", file=stream)
        print("    docron --disable <job>   ·   docron --enable <job>", file=stream)
    print("=" * width, file=stream)
    print("", file=stream)


def as_json(cron: CronFile) -> str:
    return json.dumps({
        "path": cron.path,
        "customised": cron.customised,
        "jobs": [{
            "id": job.job_id,
            "script": job.script,
            "active": job.active,
            "schedule": job.schedule,
            "schedule_human": humanise(job.schedule),
            "user": job.user,
            "log": job.log_path,
            "last_run": last_run(job),
        } for job in cron.jobs],
    }, indent=2)


# ==============================================================================
# CLI
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Overview and editing of /etc/cron.d/myodoo-maintenance.")
    parser.add_argument("--path", default=CRON_PATH,
                        help="cron file to operate on (default: %(default)s)")
    parser.add_argument("--brief", action="store_true",
                        help="compact overview, as printed by ups")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output; implies no editing")
    parser.add_argument("--set", metavar="JOB",
                        help="job to change, e.g. container2backup.py:1")
    parser.add_argument("--schedule", metavar="EXPR",
                        help="new schedule for --set, e.g. '0 3 * * *'")
    parser.add_argument("--enable", metavar="JOB", help="switch a job back on")
    parser.add_argument("--disable", metavar="JOB", help="switch a job off")
    parser.add_argument("--version", action="version",
                        version=f"ownerp_cron.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cron = load(args.path)
    except CronError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(as_json(cron))
        return 0

    mutations = [bool(args.set), bool(args.enable), bool(args.disable)]
    if sum(mutations) > 1:
        print("✗ --set, --enable and --disable are mutually exclusive",
              file=sys.stderr)
        return 2

    try:
        if args.set:
            if not args.schedule:
                print("✗ --set needs --schedule", file=sys.stderr)
                return 2
            job, backup = set_schedule(cron, args.set, args.schedule)
            print(f"✓ {job.job_id} now runs {humanise(job.schedule)} "
                  f"({job.schedule})")
            print(f"  backup: {backup}")
        elif args.enable or args.disable:
            target = args.enable or args.disable
            job, backup = set_active(cron, target, bool(args.enable))
            state = "enabled" if job.active else "switched off"
            print(f"✓ {job.job_id} {state}")
            print(f"  backup: {backup}")
        else:
            print_report(cron, brief=args.brief)
            return 0
    except CronError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"✗ cannot write {args.path}: {exc}", file=sys.stderr)
        return 1

    print_report(load(args.path), brief=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
