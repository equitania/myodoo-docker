#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_mute.py
# Description:      Mark a readiness finding as true but not applicable on this
#                   host, permanently and with a reason.
# Version:          1.0.0
# Date:             21.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   Some readiness findings are correct and still describe nothing wrong. A host
#   whose certificates come from an internal CA gets a permanent certbot-timer
#   WARN; a test server with no backups by design gets a permanent Backup-recency
#   FAIL that mails every Monday.
#
#   The cost is not the noise. An operator who learns that two lines are always
#   there stops reading the block, and the third line - the one that matters -
#   goes with them.
#
# What it does:
#   Owns the write path for /root/.config/myodoo-docker/readiness-mutes.conf.
#   Reading lives in server-readiness.py, which runs on hosts where this script
#   has not been delivered yet; a reader that could be absent would silently
#   stop every mute from applying.
#
#   ownerp_mute.py --list
#   ownerp_mute.py <check_id> --reason "<text>"
#   ownerp_mute.py --unmute <check_id>
#
# Design: docs/superpowers/specs/2026-08-21-readiness-mute-design.md
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
import importlib.util
import os
import shutil
import sys
import time
from typing import List, Optional

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "21.08.2026"

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER = """\
# Readiness checks muted on this host.
#
# A muted check still runs and still shows its line in the full report; it
# carries no weight in `chk --brief`, in the Monday cron mail or in the exit
# code. Managed by ownerp_mute.py - hand edits are read back fine.
#
# Format:  <check_id> | <YYYY-MM-DD> | <reason>
"""


class MuteError(Exception):
    """Anything that must stop a write, with a sentence for the operator."""


class ReaderUnavailable(MuteError):
    """server-readiness.py cannot be loaded, so nothing here can run.

    Its own class rather than a distinguishing phrase in the message: main()
    maps it to a different exit code, and a control-flow decision that reads
    a sentence written for humans breaks the moment that sentence is reworded.
    """


def _readiness():
    """server-readiness.py, imported by path. It owns the reader.

    By path because the name carries a hyphen and it is not on the import path:
    on a server it sits beside this file in $HOME, in the repository in scripts/.
    """
    path = os.path.join(HERE, "server-readiness.py")
    try:
        spec = importlib.util.spec_from_file_location("server_readiness", path)
        if spec is None or spec.loader is None:
            raise MuteError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except MuteError:
        raise
    except Exception as exc:
        raise ReaderUnavailable(f"server-readiness.py is not usable ({exc}) — run ups")


def _context(home: str):
    sr = _readiness()
    return sr, sr.HealthContext(home=home, repo=os.path.join(home, "myodoo-docker"))


def mutes_path(home: str) -> str:
    sr, ctx = _context(home)
    return sr.mutes_path(ctx)


def load(home: str) -> List:
    """The entries currently in the file. Reading goes through the reader."""
    sr, ctx = _context(home)
    return sr.read_mutes(ctx)


def check_ids(home: str) -> List[str]:
    """Every check_id the report can actually produce.

    A check_id does not exist until its check has run: CHECKS is a tuple of
    functions and the id lives in the Finding each returns. So the checks are
    run - read-only, a second or two - rather than kept in a second list that
    can drift away from the findings the report really emits. A mute pointing
    at an id nothing emits is exactly the silent failure this guards against.
    """
    sr, ctx = _context(home)
    return sorted({finding.check_id for finding in sr.run_checks(ctx)})


def render(entries: List) -> str:
    """The file, column-aligned so it stays readable when hand-edited."""
    width = max((len(entry.check_id) for entry in entries), default=0)
    lines = [HEADER]
    for entry in sorted(entries, key=lambda item: item.check_id):
        lines.append(f"{entry.check_id.ljust(width)} | {entry.since} | {entry.reason}")
    return "\n".join(lines) + "\n"


def _verify(sr, text: str, expected: List) -> None:
    """Re-parse what is about to be written and confirm it says the same thing.

    Separate function because the atomicity test replaces it: the failure that
    must be exercised is a write that gets as far as the temp file and is then
    rejected, and there is no malformed input that can produce it - render()
    refuses those inputs earlier.
    """
    parsed = sr.parse_mutes(text)
    if len(parsed) != len(expected):
        raise MuteError(f"refusing to write: {len(expected)} entries in, "
                        f"{len(parsed)} read back")
    for got, want in zip(sorted(parsed, key=lambda item: item.check_id),
                         sorted(expected, key=lambda item: item.check_id)):
        if (got.check_id, got.since, got.reason) != (want.check_id, want.since, want.reason):
            raise MuteError(f"refusing to write: {want.check_id} would not read back")


def write(home: str, entries: List) -> str:
    """Persist the file. Returns the backup path, or "" if there was none.

    Order matters and is the whole point: backup first, then a temp file in the
    same directory (so the rename is atomic and cannot cross a filesystem), then
    validate what was actually written by re-parsing it, and only then replace.
    A failure at any step removes the temp file and leaves the original as it was.
    """
    sr, _ctx = _context(home)
    path = mutes_path(home)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)

    backup = ""
    if os.path.exists(path):
        backup = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(path, backup)

    text = render(entries)
    temp = f"{path}.tmp_{os.getpid()}"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
        # Before the rename, never after: the file must not exist at its final
        # name with the wrong mode, however briefly.
        os.chmod(temp, 0o600)
        _verify(sr, text, entries)
        os.replace(temp, path)
    except Exception:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return backup


def mute(home: str, check_id: str, reason: str,
         valid_ids: Optional[List[str]] = None) -> str:
    """Add or replace one entry. Returns the backup path."""
    sr = _readiness()
    check_id = (check_id or "").strip()
    reason = (reason or "").strip()

    if not check_id:
        raise MuteError("no check to mute")
    if not reason:
        # The only field that makes the entry survivable. An entry nobody can
        # justify a year later gets removed rather than understood, which brings
        # the message back on a host that decided against it.
        raise MuteError(f"{check_id}: a reason is required — "
                        f'ownerp_mute.py {check_id} --reason "why it does not apply here"')
    if sr.MUTE_SEPARATOR in check_id or "\n" in check_id:
        raise MuteError(f"{check_id!r} is not a valid check id")
    if "\n" in reason:
        raise MuteError("the reason must be a single line")
    if check_id in sr.UNMUTABLE:
        raise MuteError(f"{check_id} cannot be muted: it reports mutes that no "
                        f"longer match a check, and muting it would switch off "
                        f"the guard against silent mutes")
    if valid_ids is not None and check_id not in valid_ids:
        raise MuteError(f"unknown check: {check_id}\nvalid ids: "
                        + ", ".join(sorted(valid_ids)))

    entries = [entry for entry in load(home) if entry.check_id != check_id]
    entries.append(sr.MuteEntry(check_id, time.strftime("%Y-%m-%d"), reason))
    return write(home, entries)


def unmute(home: str, check_id: str) -> str:
    """Remove one entry. Returns the backup path."""
    check_id = (check_id or "").strip()
    entries = load(home)
    remaining = [entry for entry in entries if entry.check_id != check_id]
    if len(remaining) == len(entries):
        raise MuteError(f"{check_id} is not muted on this host")
    return write(home, remaining)


# ==============================================================================
# Command line
# ==============================================================================

def format_list(entries: List) -> str:
    if not entries:
        return "No checks are muted on this host."
    width = max(len(entry.check_id) for entry in entries)
    lines = [f"{len(entries)} muted on this host:", ""]
    for entry in sorted(entries, key=lambda item: item.check_id):
        lines.append(f"  {entry.check_id.ljust(width)}  since {entry.since}  {entry.reason}")
    lines += ["", "  Unmute: ownerp_mute.py --unmute <check_id>"]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark a readiness finding as not applicable on this host.",
        epilog="A muted check still runs and still shows its line in the full "
               "report; it just carries no weight.",
    )
    parser.add_argument("check_id", nargs="?", help="the check to mute")
    parser.add_argument("--reason", help="why it does not apply here (required)")
    parser.add_argument("--unmute", metavar="CHECK_ID", help="remove a mute")
    parser.add_argument("--list", action="store_true", dest="list_entries",
                        help="show what is muted on this host")
    parser.add_argument("--home", default=None,
                        help="where the configuration lives (default: ~)")
    parser.add_argument("--no-verify-id", action="store_true",
                        help="skip checking the id against the readiness report")
    parser.add_argument("--version", action="version",
                        version=f"ownerp_mute.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    home = args.home or os.path.expanduser("~")

    try:
        if args.list_entries:
            print(format_list(load(home)))
            return 0

        if args.unmute:
            backup = unmute(home, args.unmute)
            print(f"{args.unmute} is no longer muted. "
                  f"Backup: {os.path.basename(backup)}")
            return 0

        if not args.check_id:
            build_parser().print_help()
            return 0

        # Running the checks to learn the valid ids costs a second or two, so it
        # is skippable - but it is the default, because a typo that lands in the
        # file is silent until somebody wonders why the message came back.
        valid = None if args.no_verify_id else check_ids(home)
        backup = mute(home, args.check_id, args.reason or "", valid)
        where = f"Backup: {os.path.basename(backup)}" if backup else "New file."
        print(f"{args.check_id} is muted on this host. {where}")
        print("It still runs and still shows in `chk`; it no longer counts.")
        return 0

    except ReaderUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MuteError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"cannot write the mute file: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
