#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            docker_table.py
# Description:      `docker ps` as a readable table — the renderer behind
#                   dps and dpsall.
# Version:          1.0.0
# Date:             14.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   `docker ps --format table ... | sort` sorted the header line along with the
#   containers. Under a UTF-8 locale "NAMES" collates after "ivy-odoo", so
#   the column titles landed at the bottom of the list — on every ownERP server,
#   every time. Sorting the rows without the header is the whole reason this
#   file was written; the frame and the colours are what it does afterwards.
#
# What it never does:
#   Anything but read. No container is started, stopped, removed or inspected
#   beyond the single `docker ps -a` this makes. It is `dps`, not a management
#   tool, and an operator must be able to run it on a production host without
#   thinking about it.
#
# The rule the port column is built around:
#   A shortened port must never hide that a port is reachable from outside.
#   "127.0.0.1:11600->8069/tcp" carries one bit an operator cares about — the
#   bind address — and dropping it silently would make a public port look like
#   a loopback one. Loopback binds lose the address (they are the norm here),
#   everything else keeps a visible marker: "*:8080->80" for a wildcard bind,
#   the literal address for a specific one, and both are coloured.
#
# Degrading:
#   No colour when stdout is not a terminal, ASCII box characters when the
#   output encoding cannot carry the frame, no truncation when the width is
#   unknown. Docker's own error text is passed through untouched with its exit
#   code — this must not turn "cannot connect to the daemon" into a traceback.
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
import re
import shutil
import subprocess
import sys

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "14.08.2026"


# ==============================================================================
# Columns
# ==============================================================================

# (title, docker template, shrinkable)
#
# NAME and STATUS are never shrunk: a truncated container name cannot be typed
# into `docker exec`, and a truncated status is the one thing the table exists
# to show.
BASIC = [
    ("NAME",    "{{.Names}}",  False),
    ("IMAGE",   "{{.Image}}",  True),
    ("STATUS",  "{{.Status}}", False),
    ("PORTS",   "{{.Ports}}",  True),
]

DETAILED = [
    ("NAME",    "{{.Names}}",     False),
    ("ID",      "{{.ID}}",        False),
    ("IMAGE",   "{{.Image}}",     True),
    ("COMMAND", "{{.Command}}",   True),
    ("CREATED", "{{.CreatedAt}}", True),
    ("STATUS",  "{{.Status}}",    False),
    ("PORTS",   "{{.Ports}}",     True),
]

MIN_WIDTH = 6      # a shrunk column never gets narrower than this
ELLIPSIS = "…"


# ==============================================================================
# Presentation primitives
# ==============================================================================

class Cell:
    """A table cell as coloured fragments.

    Padding is computed from the plain text, never from the rendered string —
    ANSI escapes have length but no width, and mixing the two is how coloured
    tables come out ragged.
    """

    def __init__(self, fragments=None):
        # list of (text, colour-key or None)
        self.fragments = list(fragments or [])

    @classmethod
    def plain(cls, text, colour=None):
        return cls([(text, colour)])

    @property
    def text(self):
        return "".join(f for f, _ in self.fragments)

    def render(self, width, palette, ellipsis=ELLIPSIS):
        """The cell padded to `width`, truncated with an ellipsis if longer."""
        out, used = [], 0
        for fragment, colour in self.fragments:
            if used >= width:
                break
            room = width - used
            if len(fragment) > room:
                # The clip is not belt-and-braces: with the ASCII ellipsis
                # ("...") a room of 1 or 2 would otherwise overflow the column
                # and shift the whole frame one character to the right.
                keep = max(0, room - len(ellipsis))
                fragment = (fragment[:keep] + ellipsis)[:room]
            used += len(fragment)
            code = palette.get(colour or "", "")
            out.append(f"{code}{fragment}{palette['reset']}" if code else fragment)
        return "".join(out) + " " * (width - used)


BOX_UNICODE = {"h": "─", "v": "│", "tl": "┌", "tm": "┬", "tr": "┐",
               "ml": "├", "mm": "┼", "mr": "┤",
               "bl": "└", "bm": "┴", "br": "┘",
               "dot": "●", "sep": "·", "arrow": "→", "ell": ELLIPSIS}

BOX_ASCII = {"h": "-", "v": "|", "tl": "+", "tm": "+", "tr": "+",
             "ml": "+", "mm": "+", "mr": "+",
             "bl": "+", "bm": "+", "br": "+",
             "dot": "*", "sep": "-", "arrow": "->", "ell": "..."}


def glyphs(stream):
    """Unicode frame unless the output encoding cannot carry it."""
    encoding = getattr(stream, "encoding", None) or ""
    try:
        BOX_UNICODE["h"].encode(encoding or "ascii")
    except (LookupError, UnicodeEncodeError):
        return BOX_ASCII
    return BOX_UNICODE


def palette(stream, colour=None):
    """Colour codes, or empty strings when the output is not a terminal."""
    if colour is None:
        colour = hasattr(stream, "isatty") and stream.isatty()
    if not colour:
        return {k: "" for k in
                ("green", "yellow", "red", "grey", "bold", "reset")}
    return {"green": "\033[0;32m", "yellow": "\033[1;33m", "red": "\033[0;31m",
            "grey": "\033[0;90m", "bold": "\033[1m", "reset": "\033[0m"}


def terminal_width(stream, override=None):
    """Available width, or None when there is nothing to fit into.

    A pipe has no width. Truncating for an unknown terminal would throw away
    information nobody asked to lose, so a non-tty stream gets the full table.
    """
    if override:
        return override
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return None
    return shutil.get_terminal_size((120, 24)).columns


# ==============================================================================
# Cell content
# ==============================================================================

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
WILDCARD = {"0.0.0.0", "::", ""}

# host:hostport->containerport/proto — the host part is optional and may be a
# bracketed IPv6 address or the bare "::" Docker prints for the IPv6 wildcard.
PORT_RE = re.compile(r"^(?:(?P<host>.*):)?"
                     r"(?P<hport>\d+(?:-\d+)?)->"
                     r"(?P<cport>\d+(?:-\d+)?)/(?P<proto>\w+)$")


def compact_port(mapping, arrow="→"):
    """One port mapping, shortened. Returns (text, public).

    `public` drives the colour: it is True whenever the port is reachable from
    anywhere but the host itself. An exposed-but-unpublished port ("5432/tcp")
    is returned untouched — there is nothing to shorten and nothing to warn
    about.
    """
    match = PORT_RE.match(mapping)
    if not match:
        return mapping, False

    host = (match.group("host") or "").strip("[]")
    hport, cport = match.group("hport"), match.group("cport")
    proto = match.group("proto")
    suffix = "" if proto == "tcp" else f"/{proto}"

    if host in LOOPBACK:
        return f"{hport}{arrow}{cport}{suffix}", False
    if host in WILDCARD:
        return f"*:{hport}{arrow}{cport}{suffix}", True
    return f"{host}:{hport}{arrow}{cport}{suffix}", True


def ports_cell(raw, arrow="→"):
    """The PORTS column: shortened, de-duplicated, public binds coloured.

    De-duplication matters because Docker prints a dual-stack publish twice
    ("0.0.0.0:80->80/tcp, :::80->80/tcp"), and both collapse to the same text.
    """
    cell = Cell()
    seen = set()
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        text, public = compact_port(part, arrow)
        if text in seen:
            continue
        seen.add(text)
        if cell.fragments:
            cell.fragments.append((", ", None))
        cell.fragments.append((text, "yellow" if public else None))
    return cell


def status_colour(status):
    low = status.lower()
    if "(unhealthy)" in low:
        return "red"
    if "health: starting" in low:
        return "yellow"
    if low.startswith("up"):
        return "green"
    if low.startswith(("exited", "dead")):
        return "red"
    if low.startswith(("created", "paused", "restarting", "removing")):
        return "yellow"
    return "grey"


def status_cell(status, dot="●"):
    colour = status_colour(status)
    return Cell([(f"{dot} ", colour), (status, None)])


def is_running(status):
    return status.lower().startswith("up")


# ==============================================================================
# Data
# ==============================================================================

def docker_ps(columns, runner=None):
    """The raw rows, sorted by name.

    Raises DockerError with docker's own message and exit code — this script
    has nothing better to say about a daemon that is not running than the
    daemon does.
    """
    template = "\t".join(t for _, t, _ in columns)
    runner = runner or _run
    code, out, err = runner(["docker", "ps", "-a", "--format", template])
    if code != 0:
        raise DockerError(err or out or "docker ps failed", code)

    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        # Never let a short line shift the columns; pad instead.
        fields += [""] * (len(columns) - len(fields))
        rows.append(fields[:len(columns)])
    rows.sort(key=lambda r: r[0].lower())
    return rows


class DockerError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def _run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        raise DockerError("docker: command not found", 127)
    except OSError as error:
        raise DockerError(f"docker: {error}", 1)
    return result.returncode, result.stdout, result.stderr.strip()


# ==============================================================================
# Layout
# ==============================================================================

def build_cells(rows, columns, box):
    """Raw fields to Cells, one list per row."""
    titles = [title for title, _, _ in columns]
    table = []
    for row in rows:
        cells = []
        for title, value in zip(titles, row):
            if title == "PORTS":
                cells.append(ports_cell(value, box["arrow"]))
            elif title == "STATUS":
                cells.append(status_cell(value, box["dot"]))
            else:
                cells.append(Cell.plain(value))

        table.append(cells)
    return table


def column_widths(table, columns, available):
    """Natural widths, shrunk to fit.

    Shrinking takes from the widest column of the current pool and repeats, so
    one very wide PORTS column is cut back before a merely long IMAGE is
    touched at all.

    Two pools, in order: the columns marked shrinkable, and then — only once
    those are down to MIN_WIDTH — every column. NAME and STATUS are protected,
    not sacred: on a narrow terminal a truncated status still reads, while a
    frame three characters too wide wraps and the table stops being one.
    """
    titles = [title for title, _, _ in columns]
    widths = [len(t) for t in titles]
    for cells in table:
        for index, cell in enumerate(cells):
            widths[index] = max(widths[index], len(cell.text))

    if available is None:
        return widths

    # frame: "│ " + " │ " between columns + " │"
    overhead = 4 + 3 * (len(widths) - 1)
    pools = ([i for i, (_, _, ok) in enumerate(columns) if ok],
             list(range(len(widths))))
    for pool in pools:
        while sum(widths) + overhead > available:
            candidates = [i for i in pool if widths[i] > MIN_WIDTH]
            if not candidates:
                break
            widths[max(candidates, key=lambda i: widths[i])] -= 1
    return widths


# ==============================================================================
# Rendering
# ==============================================================================

def render(rows, columns, stream, colour=None, width=None):
    box = glyphs(stream)
    c = palette(stream, colour)
    table = build_cells(rows, columns, box)
    widths = column_widths(table, columns, terminal_width(stream, width))

    def rule(left, middle, right):
        return left + middle.join(box["h"] * (w + 2) for w in widths) + right

    print(rule(box["tl"], box["tm"], box["tr"]), file=stream)

    titles = [title for title, _, _ in columns]
    header = f" {box['v']} ".join(
        f"{c['bold']}{t[:w].ljust(w)}{c['reset']}" if c['bold']
        else t[:w].ljust(w)
        for t, w in zip(titles, widths))
    print(f"{box['v']} {header} {box['v']}", file=stream)
    print(rule(box["ml"], box["mm"], box["mr"]), file=stream)

    for cells in table:
        line = f" {box['v']} ".join(
            cell.render(w, c, box["ell"]) for cell, w in zip(cells, widths))
        print(f"{box['v']} {line} {box['v']}", file=stream)

    print(rule(box["bl"], box["bm"], box["br"]), file=stream)
    print(summary(rows, columns, c, box["sep"]), file=stream)


def summary(rows, columns, c, sep="·"):
    """One line under the table: how many, and how many of them are up."""
    status_index = [t for t, _, _ in columns].index("STATUS")
    total = len(rows)
    running = sum(1 for row in rows if is_running(row[status_index]))
    stopped = total - running
    stopped_colour = c["red"] if stopped else c["grey"]
    return (f"  {c['grey']}{total} container{'s' if total != 1 else ''} "
            f"{sep}{c['reset']} {c['green']}{running} running{c['reset']} "
            f"{c['grey']}{sep}{c['reset']} {stopped_colour}{stopped} stopped"
            f"{c['reset']}")


# ==============================================================================
# Entry point
# ==============================================================================

def main(argv=None, stream=None):
    stream = stream or sys.stdout
    parser = argparse.ArgumentParser(
        description="docker ps as a readable table (dps / dpsall)")
    parser.add_argument("--details", action="store_true",
                        help="add ID, COMMAND and CREATED columns (dpsall)")
    parser.add_argument("--no-color", "--no-colour", dest="colour",
                        action="store_false", default=None,
                        help="never emit colour codes")
    parser.add_argument("--width", type=int, default=None,
                        help="assume this terminal width instead of detecting it")
    parser.add_argument("--version", action="version",
                        version=f"docker_table.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    args = parser.parse_args(argv)

    columns = DETAILED if args.details else BASIC
    try:
        rows = docker_ps(columns)
    except DockerError as error:
        print(str(error), file=sys.stderr)
        return error.code

    if not rows:
        c = palette(stream, args.colour)
        print(f"  {c['grey']}no containers{c['reset']}", file=stream)
        return 0

    render(rows, columns, stream, colour=args.colour, width=args.width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
