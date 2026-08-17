#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            odoo_build_cache.py
# Description:      Share one host-side cache of Odoo release archives across
#                   every instance on the server, so a build downloads only
#                   what actually changed.
# Version:          1.6.0
# Date:             17.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   build_odoo.py runs INSIDE the build container and downloads every archive
#   named in release.file on every build — several hundred of them, ten to
#   twenty minutes, even when a single module changed. Nothing survives the
#   build: the archives are deleted in its cleanup step, and the Docker layer
#   that held them is removed by the `docker system prune -f` that
#   update_docker_odoo.py runs after each pass. The same objection applies to a
#   BuildKit cache mount, which that prune also clears.
#
#   The archive names carry their version, so the file name is a valid cache
#   key: if the name is present, the content is right. No revalidation, no
#   conditional GET, no metadata to keep in sync.
#
# What it does:
#   sync <build-dir>   read release.file, fetch what is missing into the cache,
#                      hardlink everything into <build-dir>/zips/, and bring the
#                      build folder's Dockerfile and odoo.conf up to date
#                      (--reference)
#   gc [--days N]      drop archives unused for N days, plus old release.file-*
#   stats              size and file count per release
#
# The Dockerfile part is here because nothing else distributes it: update_
# docker_odoo.py syncs build_odoo.py, check_dockerimage_odoo.py and bin/ from
# the repository, but a build folder's Dockerfile is the customer's file and is
# never overwritten. A directive added to the repository after that folder was
# created — HEALTHCHECK, March 2026 — therefore never arrives. `sync
# --reference <repo Dockerfile>` inserts the image directives that are missing,
# aligns an ADD with the COPY the reference carries where the two are the same
# operation, and reports everything else it finds instead of touching it.
#
# The odoo.conf beside that reference is treated the same way and for the same
# reason: it is never distributed either — it holds the customer's passwords —
# so http_interface, which Odoo 19 warns about and Odoo 20 will default to
# 127.0.0.1, would stay unset on every installation that predates it. Only the
# keys in MANAGED_CONF_KEYS are filled in, and only where nothing is set.
#
# The cache is an OPTIMISATION and never a new point of failure: every failure
# path leaves the archives to build_odoo.py, which downloads them exactly as it
# did before. `sync` therefore exits 0 even when it achieved nothing at all.
#
# "Last used" is the file's mtime, refreshed on every hit — so the cleanup is a
# plain age check with no index file to keep consistent between parallel runs.
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
import csv
import os
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlsplit

SCRIPT_VERSION = "1.6.0"
SCRIPT_DATE = "17.08.2026"

CACHE_ROOT_DEFAULT = "/opt/odoo-build-cache"
ZIP_DIR = "zips"

# The archives are bind-mounted into the build step, not COPYed. Docker layers
# are additive: a COPY of ~270MB stays in the image no matter what a later RUN
# deletes, so copying would inflate every image by the full size of the release.
# A bind mount exists only while the RUN executes and leaves no layer behind.
MOUNT_FLAG = "--mount=type=bind,source=zips,target=/opt/odoo/zips"
RUN_PREFIX = "RUN cd /opt/odoo/"

# Earlier attempts, removed from a Dockerfile that still carries them.
# sync_build_scripts() in update_docker_odoo.py does not distribute Dockerfiles,
# so a correction would otherwise never reach an existing installation.
LEGACY_COPY_LINES = (
    "COPY zips/ /opt/odoo/zips/",
    "COPY --chown=odoo:odoo zips/ /opt/odoo/zips/",
)

# Only comments this script wrote itself are removed along with a legacy COPY.
# A customer's own comment above that line must survive — losing an instruction
# note is a real cost, an orphaned comment of ours is not.
OWN_COMMENT_MARKERS = ("odoo_build_cache.py", "build_odoo.py downloads",
                       "--chown is required")

# Directives that describe the finished image rather than build it. Inserting
# one changes no other instruction's behaviour, so a missing one can be filled
# in from the reference Dockerfile — HEALTHCHECK is why this exists: it entered
# the repository long after most build folders were created, and nothing ever
# carried it to them. Everything else stays the customer's to change.
ADDITIVE_KEYWORDS = ("VOLUME", "HEALTHCHECK", "EXPOSE")

# Comparing these against the reference would only produce noise: the base
# image is per-installation (check_dockerimage_odoo.py rewrites it on every
# run) and the label carries no build behaviour.
UNCOMPARED_KEYWORDS = ("FROM", "LABEL")
MISSING_REPORTED_MAX = 5

# Instructions the reference Dockerfile carries for the installations that need
# them, and whose absence is therefore not a defect to report. ca-certificates/
# exists for an installation whose LDAP/AD server presents a certificate from an
# internal CA; most have none. They cannot be added automatically either: the
# COPY needs a ca-certificates/ directory in the build folder, and inserting the
# instruction without it would break every build there. So a new installation
# gets them from the repository Dockerfile, an existing one is patched by hand
# together with the directory — and neither is nagged in between. Reporting them
# on every run is exactly what teaches people to ignore these warnings, which is
# how the one that matters gets missed.
OPTIONAL_INSTRUCTIONS = (
    "COPY ca-certificates/ /usr/local/share/ca-certificates/",
    "RUN update-ca-certificates",
)

# ADD and COPY are the same operation for a plain local path, which makes the
# July 2026 move of bin/ from ADD to COPY the one rewrite of a line's content
# that can be applied without changing what the build does. They stop being the
# same when ADD would unpack a local archive or fetch a remote source, so those
# stay untouched — as does a glob, which may resolve to either.
ADD_ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2",
                        ".tar.xz", ".txz", ".tar.zst", ".tzst", ".gz", ".bz2",
                        ".xz", ".zst", ".zip")
ADD_REMOTE_PREFIXES = ("http://", "https://", "git://", "git@", "ssh://")
# Everything ADD accepts beyond these changes what it fetches or verifies, so a
# line carrying one of them is not a plain file copy any more.
ADD_KEPT_FLAGS = ("--chown=", "--chmod=", "--link")
ADD_GLOB_CHARACTERS = "*?["

# odoo.conf is the customer's file — it carries their admin and database
# passwords, their worker count, their dbfilter — so update_docker_odoo.py never
# distributes it, and a setting the repository adds later never arrives. These
# are the keys that may be filled in from the template, at the same bar as the
# Dockerfile: a value whose effect on a running instance is nil, written only
# where the customer has set none of their own.
#
# http_interface is the case that prompted this. Odoo 19 warns when it is unset,
# and Odoo 20 will default it to 127.0.0.1 — which leaves a container
# unreachable through its published port. Writing the value Odoo uses today
# changes nothing today and prevents that.
MANAGED_CONF_KEYS = ("http_interface",)
CONF_COMMENT_PREFIXES = (";", "#")

GC_DAYS_DEFAULT = 30
RELEASE_ARCHIVES_KEPT = 5

# Same character rule as build_odoo.py: the CSV is downloaded input, and a
# manipulated entry must not be able to escape the cache directory.
SAFE_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")


def is_safe_name(name):
    """Whether an archive name from the CSV is safe to use as a path.

    The character class alone is not enough: it permits both '.' and '/', so
    '../../etc/passwd' matches it. Traversal segments and absolute paths are
    rejected explicitly — build_odoo.py's _validate_csv_filename() has the same
    gap, where the name reaches open() and unzip -d.
    """
    if not name or not SAFE_NAME.match(name):
        return False
    if name.startswith("/"):
        return False
    return ".." not in name.split("/")

# Retry policy, deliberately sharing build_odoo.py's environment variables so a
# server tuned for a slow link behaves the same in both places.
BACKOFF_CAP = 60.0
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
TIMEOUT = 300


def _attempts():
    """Read per call, not at import: tests shorten it, and a long-running cron
    picking up a changed environment should not need a restart."""
    return max(1, int(os.environ.get("BUILD_ODOO_RETRIES", "5")))


def _backoff_base():
    return max(0.5, float(os.environ.get("BUILD_ODOO_RETRY_BACKOFF", "3")))


def _failure_limit():
    return max(1, int(os.environ.get("BUILD_ODOO_FAILURE_LIMIT", "3")))


def _retry_delay(attempt):
    return min(_backoff_base() * (2 ** (attempt - 1)), BACKOFF_CAP)


def cache_root():
    """Cache location. The env override exists so tests never touch /opt."""
    return os.environ.get("ODOO_BUILD_CACHE") or CACHE_ROOT_DEFAULT


def parse_release_file(path):
    """Return (base_url, archive_names) from a release.file.

    Layout: line 1 is the base URL, line 2 the Docker image (ignored here),
    line 3 the kernel archive, everything after that a module archive. Blank
    rows do not consume a position, so a stray empty line cannot shift the
    kernel into the ignored slot.
    """
    base_url = None
    names = []
    index = 0
    with open(path, encoding="utf8") as handle:
        for row in csv.reader(handle, delimiter=","):
            if not row:
                continue
            column = row[0].replace(" ", "")
            if not column:
                continue
            index += 1
            if index == 1:
                base_url = column
            elif index == 2:
                continue
            elif is_safe_name(column):
                names.append(column)
            else:
                print(f"Ignoring unsafe entry in release file: '{column}'")
    if not base_url or base_url == "False":
        raise ValueError(f"{path}: no base URL in line 1")
    return base_url, names


def cache_path_for(root, base_url, name):
    """Absolute path of one archive inside the cache.

    Partitioned by host and URL path, so two Odoo versions can ship an archive
    of the same name without overwriting each other, while two instances on the
    same release share every file.
    """
    if not is_safe_name(name):
        raise ValueError(f"unsafe archive name: {name!r}")
    split = urlsplit(base_url)
    parts = [part for part in split.path.split("/") if part]
    return os.path.join(root, split.netloc, *parts, name)


def _download(url, destination):
    """Fetch url to destination. Returns (ok, error, retryable)."""
    try:
        # urllib.request honours http_proxy/https_proxy from the environment on
        # its own — unlike urllib3, which needs an explicit ProxyManager.
        context = ssl.create_default_context()
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=context) as response:
            with open(destination, "wb") as handle:
                shutil.copyfileobj(response, handle)
        return True, None, False
    except urllib.error.HTTPError as error:
        return False, f"HTTP status {error.code}", error.code in RETRYABLE_STATUS
    except Exception as error:                       # URLError, socket, ssl, OSError
        return False, f"{type(error).__name__}: {error}", True


def fetch_into_cache(base_url, name, root):
    """Ensure `name` is present in the cache. True when it is, afterwards.

    A hit costs no network round trip at all: the archive names carry their
    version, so a name that is present is by definition the right content.
    """
    target = cache_path_for(root, base_url, name)
    if os.path.isfile(target):
        os.utime(target, None)                       # mtime == last used, drives gc
        return True

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except OSError as error:
        print(f"Cannot create cache directory: {error}")
        return False

    url = base_url.rstrip("/") + "/" + name
    temporary = target + ".tmp"
    last_error = None
    attempts = _attempts()

    for attempt in range(1, attempts + 1):
        ok, last_error, retryable = _download(url, temporary)
        if ok:
            # A release server answering an error with a 200 HTML page would
            # otherwise poison the cache permanently — unlike today, where the
            # bad file dies with the build container.
            if not zipfile.is_zipfile(temporary):
                os.remove(temporary)
                print(f"Refused {name}: not a valid zip archive")
                return False
            os.replace(temporary, target)            # atomic; no half file on abort
            print(f"Cached: {name}")
            return True
        if not retryable:
            break
        if attempt < attempts:
            delay = _retry_delay(attempt)
            print(f"Attempt {attempt}/{attempts} for {name} failed "
                  f"({last_error}) — retrying in {delay:.0f}s...")
            sys.stdout.flush()
            time.sleep(delay)

    if os.path.exists(temporary):
        os.remove(temporary)
    print(f"Failed to cache {name}: {last_error}")
    return False


def populate_build_dir(build_dir, root, base_url, names):
    """Link every cached archive into <build_dir>/zips/. Returns (linked, missing).

    Emptied first so a leftover from a previous release cannot travel into the
    image. Hardlinks cost no space; a cache on a different filesystem falls back
    to a copy.
    """
    target_dir = os.path.join(build_dir, ZIP_DIR)
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    linked = missing = 0
    for name in names:
        source = cache_path_for(root, base_url, name)
        if not os.path.isfile(source):
            missing += 1
            continue
        destination = os.path.join(target_dir, os.path.basename(name))
        try:
            os.link(source, destination)
        except OSError:                              # EXDEV: different filesystem
            shutil.copy2(source, destination)
        linked += 1

    # Customer module archives are not part of a release and never enter the
    # cache — they are built by the customer and live in the build folder. They
    # are linked into the same directory so the build reaches them through the
    # bind mount as well; a `COPY *custom_modules.*` would otherwise keep them
    # in an image layer that no later cleanup can shrink.
    custom = 0
    for entry in sorted(os.listdir(build_dir)):
        if not entry.endswith("custom_modules.zip"):
            continue
        source = os.path.join(build_dir, entry)
        if not os.path.isfile(source):
            continue
        destination = os.path.join(target_dir, entry)
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        custom += 1
    if custom:
        print(f"Custom module archive(s) available through the mount: {custom}")
    return linked, missing


def _keyword(line):
    """The Dockerfile instruction a line starts, uppercased. '' for none."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped.split(None, 1)[0].upper()


def _find_directive(lines, keyword):
    """Index of the first line starting `keyword`, or -1."""
    for index, line in enumerate(lines):
        if _keyword(line) == keyword:
            return index
    return -1


def _block_bounds(lines, index):
    """The full extent of the instruction at `index` as a [start, end) slice.

    Continuation lines belong to it, and so does a comment block directly above
    it: in the reference Dockerfile that comment explains what the directive is
    for, and a directive copied without its explanation loses half its value.
    """
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    end = index
    while end < len(lines) and lines[end].rstrip().endswith("\\"):
        end += 1
    return start, end + 1


def _insertion_point(lines):
    """Where a missing image directive goes.

    Ahead of the entrypoint, which is where the reference keeps these — and at
    the end of the file when there is none.
    """
    for keyword in ("ENTRYPOINT", "CMD"):
        index = _find_directive(lines, keyword)
        if index != -1:
            start, _ = _block_bounds(lines, index)
            return start
    return len(lines)


def _apply_mount(lines):
    """Rewrite the build step to bind-mount the zip folder.

    Returns (changed, complete): `complete` is False only when there is nothing
    to patch at all, which is worth reporting; a file that already carries the
    mount is complete and unchanged.
    """
    if any(MOUNT_FLAG in line for line in lines):
        return False, True

    changed = False

    # Drop a legacy COPY, plus a comment block above it that this script wrote.
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() not in LEGACY_COPY_LINES:
            continue
        start = index
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            if not any(marker in lines[start - 1] for marker in OWN_COMMENT_MARKERS):
                break                      # a customer comment — stop here
            start -= 1
        end = index + 1
        if end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        changed = True

    for index, line in enumerate(lines):
        if line.startswith(RUN_PREFIX):
            # Replace only the 'RUN ' keyword and keep the rest of the line as a
            # continuation, so an instruction the customer added to this step
            # (`&& pip install ...`) survives untouched.
            lines[index] = "    " + line[len("RUN "):]
            lines.insert(index, f"RUN {MOUNT_FLAG} \\")
            return True, True

    return changed, changed


def _copy_equivalent(line):
    """`line` rewritten as COPY, or None when ADD is not equivalent here.

    None is the answer for everything that is not provably the same operation:
    a remote source ADD would fetch, a local archive it would unpack, a glob
    that may be either, a flag beyond the ones a plain copy uses, and the JSON
    form — worth parsing only if it ever shows up in a build folder.
    """
    if _keyword(line) != "ADD":
        return None
    body = line.strip()[len("ADD"):].strip()
    if body.startswith("["):
        return None
    tokens = body.split()
    flags = [token for token in tokens if token.startswith("-")]
    if any(not flag.startswith(ADD_KEPT_FLAGS) for flag in flags):
        return None
    operands = [token for token in tokens if not token.startswith("-")]
    if len(operands) < 2:
        return None
    for source in operands[:-1]:
        lowered = source.lower()
        if lowered.startswith(ADD_REMOTE_PREFIXES):
            return None
        if lowered.endswith(ADD_ARCHIVE_SUFFIXES):
            return None
        if any(character in source for character in ADD_GLOB_CHARACTERS):
            return None
    indent = line[:len(line) - len(line.lstrip())]
    return f"{indent}COPY {body}"


def _apply_add_to_copy(lines, reference_lines):
    """Align an ADD with the COPY the reference carries. Returns the rewrites.

    Narrow on purpose: the instruction must be equivalent as a copy (see
    _copy_equivalent) AND the reference must carry exactly it as a COPY. So
    this corrects what the repository itself has moved — bin/ in July 2026 —
    and nothing the customer added on their own.
    """
    wanted = {_normalise(instruction)
              for instruction in _instructions("\n".join(reference_lines))
              if _keyword(instruction) == "COPY"}
    rewrites = []
    for index, line in enumerate(lines):
        if line.rstrip().endswith("\\"):        # continuation: out of scope
            continue
        candidate = _copy_equivalent(line)
        if candidate is None or _normalise(candidate) not in wanted:
            continue
        rewrites.append((line.strip(), candidate.strip()))
        lines[index] = candidate
    return rewrites


def _apply_reference(lines, reference_lines):
    """Fill in image directives the reference has and this file lacks.

    Returns (added, missing): `added` are the instructions inserted, `missing`
    are reference instructions this file does not have and that cannot be added
    safely — an extra RUN, a changed COPY. Those are the customer's territory,
    so they are reported for a human to decide on, never applied.
    """
    added = []
    for keyword in ADDITIVE_KEYWORDS:
        source = _find_directive(reference_lines, keyword)
        if source == -1 or _find_directive(lines, keyword) != -1:
            continue
        start, end = _block_bounds(reference_lines, source)
        block = reference_lines[start:end]
        at = _insertion_point(lines)
        lines[at:at] = block + [""]
        added.extend(_instructions("\n".join(block)))

    present = [_normalise(i) for i in _instructions("\n".join(lines))]
    missing = []
    for instruction in _instructions("\n".join(reference_lines)):
        if _keyword(instruction) in UNCOMPARED_KEYWORDS:
            continue
        wanted = _normalise(instruction)
        # Opt-in instructions are not reported when absent (see the constant).
        if wanted in _OPTIONAL_NORMALISED:
            continue
        # An instruction the customer EXTENDED counts as present: their build
        # RUN reads `cd /opt/odoo/ && python3 build_odoo.py && pip3 install ...`
        # and reporting that as missing would train everyone to ignore these
        # warnings — which is how the one that matters gets missed.
        if any(have == wanted or have.startswith(wanted + " ") for have in present):
            continue
        missing.append(instruction)
    return added, missing


def ensure_dockerfile_mount(path):
    """Backwards-compatible entry point: mount patch only, no reference."""
    return ensure_dockerfile_current(path)


def ensure_dockerfile_current(path, reference=None):
    """Bring a build folder's Dockerfile up to date. True when changed.

    Three jobs, one write:

      * the build step must bind-mount the zip folder instead of COPYing it
      * every image directive the reference Dockerfile carries must be present
      * an ADD the reference carries as COPY is aligned where the two do the
        same thing

    The second job exists because sync_build_scripts() in update_docker_odoo.py
    distributes build_odoo.py, check_dockerimage_odoo.py and bin/ but never the
    Dockerfile. An installation created before a directive was introduced —
    HEALTHCHECK, added to the repository in March 2026, is the case that
    prompted this — would otherwise never receive it, no matter how often the
    server is updated. check_dockerimage_odoo.py already patches this file (FROM
    line and date), so patching it is established practice in this project.

    This file belongs to the customer, so every change here is one whose effect
    on the build is provably nil: the `RUN ` keyword is replaced by the mount
    and the rest of the line is carried over verbatim, only entirely absent
    image directives are inserted, and the sole rewrite of a line's content is
    ADD→COPY where the two are the same operation and the reference already
    carries exactly that COPY. The result is compared instruction by
    instruction against the original before it is written. Whatever cannot be
    changed safely is reported instead.
    """
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf8") as handle:
        original = handle.read()
    lines = original.splitlines()

    changed, complete = _apply_mount(lines)
    if not complete:
        print(f"Could not patch {path}: no '{RUN_PREFIX}' line found")

    added = []
    rewrites = []
    if reference and os.path.isfile(reference):
        with open(reference, encoding="utf8") as handle:
            reference_lines = handle.read().splitlines()
        # Before the comparison, so an ADD that only needs its keyword aligned
        # is corrected instead of reported for the rest of time.
        rewrites = _apply_add_to_copy(lines, reference_lines)
        added, missing = _apply_reference(lines, reference_lines)
        if added or rewrites:
            changed = True
        for instruction in missing[:MISSING_REPORTED_MAX]:
            if len(instruction) > 90:
                instruction = instruction[:89] + "…"
            print(f"Warning: Dockerfile in {os.path.dirname(path) or '.'} is missing "
                  f"a repository instruction, add it by hand: {instruction}")
        if len(missing) > MISSING_REPORTED_MAX:
            print(f"Warning: {len(missing) - MISSING_REPORTED_MAX} further "
                  f"repository instruction(s) missing from {path}")

    if not changed:
        return False

    patched = "\n".join(lines) + "\n"
    problem = _dockerfile_regression(original, patched, added, rewrites)
    if problem:
        print(f"Refusing to patch {path}: {problem}")
        return False

    backup = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    try:
        with open(backup, "w", encoding="utf8") as handle:
            handle.write(original)
    except OSError as error:
        print(f"Refusing to patch {path}: cannot write backup ({error})")
        return False

    with open(path, "w", encoding="utf8") as handle:
        handle.write(patched)
    done = []
    if MOUNT_FLAG in patched and MOUNT_FLAG not in original:
        done.append(f"build step now bind-mounts {ZIP_DIR}/")
    if added:
        done.append("added " + ", ".join(sorted({_keyword(i) for i in added})))
    if rewrites:
        done.append("aligned with the reference: "
                    + ", ".join(after for _before, after in rewrites))
    print(f"Patched {path}: {'; '.join(done)} "
          f"(backup: {os.path.basename(backup)})")
    return True


def _instructions(text):
    """Dockerfile instructions in order, continuations folded into one entry.

    Comments and blank lines are ignored — they carry no build behaviour, and
    the comparison is about what the build *does*.
    """
    folded = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if pending:
            pending += " " + line.rstrip("\\").strip()
        else:
            pending = line.rstrip("\\").strip()
        if not raw.rstrip().endswith("\\"):
            folded.append(" ".join(pending.split()))
            pending = ""
    if pending:
        folded.append(" ".join(pending.split()))
    return folded


def _normalise(instruction):
    """An instruction reduced to what it does.

    The mount is the one rewrite this script performs, so it is removed before
    comparing — with it in place, the build RUN of a patched file would never
    match its own original or the reference.
    """
    return " ".join(instruction.replace(MOUNT_FLAG, "").split())


# Built here rather than beside OPTIONAL_INSTRUCTIONS because it needs
# _normalise(), so the two spellings can never drift apart.
_OPTIONAL_NORMALISED = frozenset(_normalise(i) for i in OPTIONAL_INSTRUCTIONS)


def _dockerfile_regression(original, patched, allowed_additions=(),
                           allowed_rewrites=()):
    """Return a reason to refuse the patch, or None when it is safe.

    The Dockerfile is the customer's: it may carry extra COPY steps, a modified
    base image or additional commands. The permitted differences are the added
    mount, a removed `COPY zips/`, the image directives taken verbatim from the
    reference, and the ADD→COPY alignments announced in `allowed_rewrites` —
    nothing else may be dropped, and nothing may appear that this script did
    not deliberately insert. An alignment counts only as the exact pair that
    was announced: any other reading of it is a dropped instruction.
    """
    before = [_normalise(i) for i in _instructions(original)]
    after = [_normalise(i) for i in _instructions(patched)]

    expected_removals = [i for i in before
                         if i.replace("--chown=odoo:odoo ", "").startswith("COPY zips/")]
    rewritten = {_normalise(source): _normalise(target)
                 for source, target in allowed_rewrites}
    remaining = list(after)
    lost = []
    for instruction in before:
        if instruction in remaining:
            remaining.remove(instruction)
        elif rewritten.get(instruction) in remaining:
            remaining.remove(rewritten[instruction])
        elif instruction not in expected_removals:
            lost.append(instruction)
    if lost:
        return f"would drop instruction(s): {'; '.join(lost[:3])}"
    for instruction in allowed_additions:
        normalised = _normalise(instruction)
        if normalised in remaining:
            remaining.remove(normalised)
    if remaining:
        return f"would add unexpected instruction(s): {'; '.join(remaining[:3])}"
    return None


def _conf_key_index(lines, key):
    """Index of the line that sets `key`, or None. A comment does not set it."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(CONF_COMMENT_PREFIXES) or stripped.startswith("["):
            continue
        name, separator, _value = stripped.partition("=")
        if separator and name.strip() == key:
            return index
    return None


def _conf_values(lines):
    """The settings an odoo.conf makes, as {key: value}.

    An empty value is kept as the empty string rather than dropped, because
    that is a distinction Odoo itself makes: config.py deletes an empty
    http_interface from the file options and falls through to its default.
    """
    values = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(CONF_COMMENT_PREFIXES) or stripped.startswith("["):
            continue
        name, separator, value = stripped.partition("=")
        if separator:
            values[name.strip()] = value.strip()
    return values


def _conf_block(reference_lines, key):
    """The template's line for `key` plus the comments explaining it.

    Same reasoning as for the Dockerfile: a setting that arrives without the
    sentence saying why it is there invites the next person to remove it.
    """
    index = _conf_key_index(reference_lines, key)
    if index is None:
        return []
    start = index
    while start > 0 and reference_lines[start - 1].strip().startswith(CONF_COMMENT_PREFIXES):
        start -= 1
    return reference_lines[start:index + 1]


def _conf_regression(original, patched, allowed_keys=()):
    """Return a reason to refuse the config patch, or None when it is safe.

    Getting this wrong is worse than getting the Dockerfile wrong: a silently
    changed db_password takes the instance down at runtime, with no build to
    fail first. So every setting must survive with its value, and the only
    permitted difference is a value for one of the announced keys.
    """
    before = _conf_values(original.splitlines())
    after = _conf_values(patched.splitlines())
    allowed = set(allowed_keys)

    for key, value in before.items():
        if key in allowed:
            continue
        if key not in after:
            return f"would drop setting: {key}"
        if after[key] != value:
            return f"would change setting: {key}"
    unexpected = sorted(set(after) - set(before) - allowed)
    if unexpected:
        return f"would add setting(s): {', '.join(unexpected)}"
    return None


def ensure_odoo_conf_current(path, reference):
    """Fill in managed settings the installed odoo.conf leaves unset.

    True when the file was changed. Only MANAGED_CONF_KEYS are considered, only
    where the customer has no value of their own — an empty value counts as
    none, because Odoo treats it that way — and only the template's value is
    ever written. Everything else in the file, passwords included, is carried
    over untouched, and a backup is taken before the write.
    """
    if not os.path.isfile(path) or not reference or not os.path.isfile(reference):
        return False
    with open(path, encoding="utf8") as handle:
        original = handle.read()
    with open(reference, encoding="utf8") as handle:
        reference_lines = handle.read().splitlines()

    lines = original.splitlines()
    installed = _conf_values(lines)
    template = _conf_values(reference_lines)

    applied = []
    for key in MANAGED_CONF_KEYS:
        if not template.get(key) or installed.get(key):
            continue
        block = _conf_block(reference_lines, key)
        if not block:
            continue
        index = _conf_key_index(lines, key)
        if index is None:
            lines.extend([""] + block)
        else:
            lines[index:index + 1] = block
        applied.append(key)

    if not applied:
        return False

    patched = "\n".join(lines) + "\n"
    problem = _conf_regression(original, patched, applied)
    if problem:
        print(f"Refusing to patch {path}: {problem}")
        return False

    backup = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    try:
        with open(backup, "w", encoding="utf8") as handle:
            handle.write(original)
    except OSError as error:
        print(f"Refusing to patch {path}: cannot write backup ({error})")
        return False

    with open(path, "w", encoding="utf8") as handle:
        handle.write(patched)
    print(f"Patched {path}: set {', '.join(applied)} "
          f"(backup: {os.path.basename(backup)})")
    return True


def gc_cache(root, days):
    """Drop archives unused for `days`. Returns (removed, freed_bytes).

    Deliberately not "absent from the current release.file": another instance on
    this server may still run an older release and need exactly that archive.
    """
    if not os.path.isdir(root):
        return 0, 0
    cutoff = time.time() - days * 86400
    removed = freed = 0
    for current, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
                if stat.st_mtime < cutoff:
                    os.remove(path)
                    removed += 1
                    freed += stat.st_size
            except OSError:
                continue
        try:
            if current != root and not os.listdir(current):
                os.rmdir(current)
        except OSError:
            pass
    return removed, freed


def gc_release_archives(build_dir, keep=RELEASE_ARCHIVES_KEPT):
    """Remove all but the newest `keep` release.file-<timestamp> archives.

    check_dockerimage_odoo.py renames the previous release.file on every run and
    never deletes one, so these accumulate for the life of the server.
    """
    prefix = "release.file-"
    try:
        entries = [name for name in os.listdir(build_dir) if name.startswith(prefix)]
    except OSError:
        return 0
    paths = [os.path.join(build_dir, name) for name in entries]
    paths = [path for path in paths if os.path.isfile(path)]
    paths.sort(key=os.path.getmtime, reverse=True)
    removed = 0
    for path in paths[keep:]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed


def cmd_sync(build_dir, reference=None):
    root = cache_root()

    # Independent of the cache, and therefore done first: a folder without a
    # release.file still has a Dockerfile that may be missing its HEALTHCHECK,
    # and an odoo.conf that may be missing a setting the repository has since
    # added. The conf template is the reference Dockerfile's neighbour — both
    # live in the repository's v{N}-odoo folder.
    ensure_dockerfile_current(os.path.join(build_dir, "Dockerfile"), reference)
    if reference:
        ensure_odoo_conf_current(os.path.join(build_dir, "odoo.conf"),
                                 os.path.join(os.path.dirname(reference), "odoo.conf"))

    release = os.path.join(build_dir, "release.file")
    if not os.path.isfile(release):
        print(f"No release.file in {build_dir} — nothing to cache.")
        return 0
    try:
        base_url, names = parse_release_file(release)
    except (ValueError, OSError) as error:
        print(f"Cannot read {release}: {error}")
        return 0

    limit = _failure_limit()
    fetched = failed = consecutive = 0
    for name in names:
        if fetch_into_cache(base_url, name, root):
            fetched += 1
            consecutive = 0
        else:
            failed += 1
            consecutive += 1
            if consecutive >= limit:
                print(f"Stopping cache sync: {consecutive} downloads failed back to "
                      f"back. The build will fetch the rest itself.")
                break

    linked, missing = populate_build_dir(build_dir, root, base_url, names)
    print(f"Cache: {linked}/{len(names)} archives ready, {missing} left for the build "
          f"({failed} download(s) failed).")
    return 0                                        # never block the build


def cmd_gc(days, build_dirs):
    removed, freed = gc_cache(cache_root(), days)
    print(f"Cache: removed {removed} archive(s), freed {freed / 1024 ** 2:.1f} MB "
          f"(unused for more than {days} days).")
    for build_dir in build_dirs:
        count = gc_release_archives(build_dir)
        if count:
            print(f"{build_dir}: removed {count} old release.file archive(s).")
    return 0


def cmd_stats():
    root = cache_root()
    if not os.path.isdir(root):
        print(f"No cache at {root}.")
        return 0
    per_partition = {}
    for current, _dirs, files in os.walk(root):
        for name in files:
            try:
                size = os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
            key = os.path.relpath(current, root)
            count, total = per_partition.get(key, (0, 0))
            per_partition[key] = (count + 1, total + size)
    grand_count = sum(count for count, _ in per_partition.values())
    grand_size = sum(size for _, size in per_partition.values())
    for key in sorted(per_partition):
        count, size = per_partition[key]
        print(f"  {key}: {count} archive(s), {size / 1024 ** 2:.1f} MB")
    print(f"Total: {grand_count} archive(s), {grand_size / 1024 ** 2:.1f} MB in {root}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Zip cache for Odoo image builds",
        epilog=f"odoo_build_cache.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="fill the cache and the build folder")
    sync.add_argument("build_dir")
    sync.add_argument("--reference", metavar="DOCKERFILE",
                      help="reference Dockerfile from the repository; image "
                           "directives it carries and the build folder lacks "
                           "(HEALTHCHECK above all) are filled in, and the "
                           "odoo.conf beside it fills in managed settings")
    collect = sub.add_parser("gc", help="remove archives unused for a while")
    collect.add_argument("--days", type=int, default=GC_DAYS_DEFAULT)
    collect.add_argument("build_dir", nargs="*")
    sub.add_parser("stats", help="show cache size per release")

    args = parser.parse_args(argv)
    if args.command == "sync":
        return cmd_sync(args.build_dir, args.reference)
    if args.command == "gc":
        return cmd_gc(args.days, args.build_dir)
    return cmd_stats()


if __name__ == "__main__":
    sys.exit(main())
