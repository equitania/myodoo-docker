#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            odoo_build_cache.py
# Description:      Share one host-side cache of Odoo release archives across
#                   every instance on the server, so a build downloads only
#                   what actually changed.
# Version:          1.2.0
# Date:             04.08.2026
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
#                      hardlink everything into <build-dir>/zips/
#   gc [--days N]      drop archives unused for N days, plus old release.file-*
#   stats              size and file count per release
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

SCRIPT_VERSION = "1.2.0"
SCRIPT_DATE = "04.08.2026"

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


def ensure_dockerfile_mount(path):
    """Make the build step bind-mount the zip folder. True when changed.

    sync_build_scripts() in update_docker_odoo.py distributes build_odoo.py but
    not the Dockerfile, so a correction here would never reach an existing
    server on its own. check_dockerimage_odoo.py already patches this file (FROM
    line and date), so patching it is established practice in this project.

    Also removes the COPY line earlier versions inserted, together with OUR
    comments above it — a customer's own comment is left alone.

    This file belongs to the customer: it can carry extra COPY steps, an
    adjusted base image, or additional commands inside the very RUN this
    patches. Nothing here rewrites a line's content — the `RUN ` keyword is
    replaced by the mount, everything after it is carried over verbatim — and
    the result is checked instruction by instruction before it is written.
    """
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf8") as handle:
        original = handle.read()
    lines = original.splitlines()
    if any(MOUNT_FLAG in line for line in lines):
        return False

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
            changed = True
            break
    else:
        if not changed:
            print(f"Could not patch {path}: no '{RUN_PREFIX}' line found")
            return False

    patched = "\n".join(lines) + "\n"
    problem = _dockerfile_regression(original, patched)
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
    print(f"Patched {path}: build step now bind-mounts {ZIP_DIR}/ "
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


def _dockerfile_regression(original, patched):
    """Return a reason to refuse the patch, or None when it is safe.

    The Dockerfile is the customer's: it may carry extra COPY steps, a modified
    base image or additional commands. The only permitted differences are the
    added mount and a removed `COPY zips/`.
    """
    def without_mount(instruction):
        """The mount is the one difference this patch is allowed to make, so it
        is removed before comparing — everything else must match exactly."""
        return " ".join(instruction.replace(MOUNT_FLAG, "").split())

    before = [without_mount(i) for i in _instructions(original)]
    after = [without_mount(i) for i in _instructions(patched)]

    expected_removals = [i for i in before
                         if i.replace("--chown=odoo:odoo ", "").startswith("COPY zips/")]
    remaining = list(after)
    lost = []
    for instruction in before:
        if instruction in remaining:
            remaining.remove(instruction)
        elif instruction not in expected_removals:
            lost.append(instruction)
    if lost:
        return f"would drop instruction(s): {'; '.join(lost[:3])}"
    if remaining:
        return f"would add unexpected instruction(s): {'; '.join(remaining[:3])}"
    return None


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


def cmd_sync(build_dir):
    root = cache_root()
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
    ensure_dockerfile_mount(os.path.join(build_dir, "Dockerfile"))
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
    collect = sub.add_parser("gc", help="remove archives unused for a while")
    collect.add_argument("--days", type=int, default=GC_DAYS_DEFAULT)
    collect.add_argument("build_dir", nargs="*")
    sub.add_parser("stats", help="show cache size per release")

    args = parser.parse_args(argv)
    if args.command == "sync":
        return cmd_sync(args.build_dir)
    if args.command == "gc":
        return cmd_gc(args.days, args.build_dir)
    return cmd_stats()


if __name__ == "__main__":
    sys.exit(main())
