#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Version 3.4.0
# Date 21.08.2026
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
#    Copyright (C) 2018-now Equitania Software GmbH(<http://www.equitania.de>).
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

import io
import csv
import os
import re
import shlex
import subprocess
import sys
import time
import datetime
import platform

_access_file = 'release.txt'
_release_file = 'release.file'
_dockerfile = 'Dockerfile'

# Validation pattern for Docker image references (e.g. myodoo/prepare-v19:25.12.08-3.12.12)
_DOCKER_IMAGE_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9_.-]+$')

# Sources the Dockerfile names but that are produced elsewhere. release.file is
# downloaded by this very script a few lines further down - reporting it as a
# missing context entry would be a permanent false alarm on a healthy build.
_CONTEXT_IGNORED = {'release.file'}

# A source carrying any of these is a glob. Whether it matches anything is the
# Dockerfile author's decision (the customer-modules COPY is deliberately
# allowed to fail), so the context check stays out of it.
_GLOB_CHARS = ('*', '?', '[')

# 'RUN --mount=type=bind,source=zips,target=...' - the bind source must exist
# in the context; unlike COPY it may be an empty directory.
_BIND_SOURCE_RE = re.compile(r'--mount=[^\s]*\bsource=([^\s,]+)')

_COLUMN = 22

if platform.system() == 'Darwin':
    _sed_inplace = ["-i", ""]
else:
    _sed_inplace = ["-i"]


def _logical_lines(text):
    """Yield Dockerfile instructions with backslash continuations joined.

    Comments and blank lines are dropped. A continued instruction becomes one
    logical line, so 'RUN --mount=... \\\\\\n cd /opt/odoo' is seen as a single
    RUN carrying its mount flag.
    """
    lines = []
    buffer = ''
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith('#'):
            continue
        if not stripped:
            if not buffer:
                continue
            continue
        if stripped.endswith('\\'):
            buffer += stripped[:-1].rstrip() + ' '
            continue
        buffer += stripped
        lines.append(buffer)
        buffer = ''
    if buffer:
        lines.append(buffer)
    return lines


def parse_context_sources(dockerfile_text):
    """Extract the build-context entries a Dockerfile depends on.

    Returns a list of ``(source, creatable)`` tuples in the order they appear.
    ``creatable`` marks an entry this script may bring into existence itself
    because an EMPTY one is a valid build input:

    * a ``--mount=type=bind`` source - the mount only needs the directory
    * a COPY/ADD source written with a trailing slash - a directory copy

    Everything else (``bin``, ``build_odoo.py``, ``odoo.conf``) carries content
    that nothing here can reconstruct, so it is reported instead.

    Skipped on purpose: globs, remote URLs (ADD fetches those), ``--from=``
    sources (another build stage, not the context) and ``_CONTEXT_IGNORED``.
    """
    sources = []
    seen = set()

    def add(source, creatable):
        source = source.strip('"\'')
        if not source or source in seen or source in _CONTEXT_IGNORED:
            return
        if any(char in source for char in _GLOB_CHARS):
            return
        seen.add(source)
        sources.append((source, creatable))

    for line in _logical_lines(dockerfile_text):
        keyword = line.split(None, 1)[0].upper() if line.split() else ''

        if keyword == 'RUN':
            for match in _BIND_SOURCE_RE.finditer(line):
                add(match.group(1), True)
            continue

        if keyword not in ('COPY', 'ADD'):
            continue

        try:
            parts = shlex.split(line)[1:]
        except ValueError:
            continue
        if any(part.startswith('--from=') for part in parts):
            continue
        parts = [part for part in parts if not part.startswith('--')]
        if len(parts) < 2:
            continue
        for source in parts[:-1]:
            if '://' in source:
                continue
            add(source, source.endswith('/'))

    return sources


def check_build_context(build_dir='.', dockerfile=_dockerfile):
    """Verify the build context and create the entries that may be empty.

    Returns True when the context is complete - after creating whatever could
    be created. False means a required entry is missing that nothing here can
    produce; the build would fail on it, and saying so now beats a Docker cache
    key error later.

    Creating a directory is never a failure: an installation without an
    internal CA has no 'ca-certificates/' and must not carry a warning on every
    single build for it.
    """
    dockerfile_path = os.path.join(build_dir, dockerfile)

    print('Build context check')
    print('-------------------')

    if not os.path.isfile(dockerfile_path):
        print(f'  {dockerfile:<{_COLUMN}} MISSING -- cannot be created')
        print('')
        print(f'ERROR: no {dockerfile} in {os.path.abspath(build_dir)} - nothing to build.')
        return False

    with io.open(dockerfile_path, 'r', encoding='utf8') as handle:
        sources = parse_context_sources(handle.read())

    missing = []
    for source, creatable in sources:
        path = os.path.join(build_dir, source)
        if os.path.exists(path):
            print(f'  {source:<{_COLUMN}} ok')
            continue
        if creatable:
            try:
                os.makedirs(path)
            except OSError as exc:
                print(f'  {source:<{_COLUMN}} MISSING -- could not create: {exc}')
                missing.append(source)
                continue
            print(f'  {source:<{_COLUMN}} MISSING -> created (empty)')
            continue
        print(f'  {source:<{_COLUMN}} MISSING -- cannot be created')
        missing.append(source)

    print(f'  {dockerfile:<{_COLUMN}} ok')
    print('')

    if missing:
        plural = 'entry is' if len(missing) == 1 else 'entries are'
        print(f'ERROR: {len(missing)} required {plural} missing from the build context: '
              f'{", ".join(missing)}')
        print('The build will fail on it. Restore from the myodoo-docker repository')
        print('(Dockerfiles/v<version>-odoo/) or run: ups')
        return False

    return True


def update_dockerfile(image_ref: str) -> None:
    """Update Dockerfile FROM line and date using subprocess instead of os.system."""
    if not _DOCKER_IMAGE_PATTERN.match(image_ref):
        print(f'ERROR: Invalid Docker image reference: {image_ref}')
        print('Expected format: registry/image:tag (e.g. myodoo/prepare-v19:25.12.08-3.12.12)')
        return

    # sed would abort with a traceback here; the build folder is simply not one.
    if not os.path.isfile(_dockerfile):
        print(f'ERROR: no {_dockerfile} here - cannot set FROM {image_ref}')
        return

    current_date = datetime.datetime.now().strftime('%d.%m.%Y')

    # Update FROM line
    sed_from_cmd = ["sed"] + _sed_inplace + [f'1s|.*|FROM {image_ref}|', "Dockerfile"]
    print(f'dockerimage: {image_ref}')
    subprocess.run(sed_from_cmd, check=True)

    # Update date line
    sed_date_cmd = ["sed"] + _sed_inplace + [f'4s|# Date.*|# Date {current_date}|', "Dockerfile"]
    subprocess.run(sed_date_cmd, check=True)


def main():
    """Check the build context, then refresh the base image from the release file.

    Returns the process exit code. update_docker_odoo.py turns a non-zero code
    into a warning and carries on, so this never aborts a 'doup' - it states
    the fault where it happens instead of leaving it to the build.
    """
    context_ok = check_build_context()

    if not os.path.isfile(_access_file):
        print('*********************************************')
        print('*               E R R O R                   *')
        print('*  NO file named access_myodoo.txt found!!  *')
        print('*********************************************')
        return 0 if context_ok else 1

    _accesscode = open(_access_file).readline().rstrip()
    if _accesscode == "":
        print('Not valid accesscode :(')
        return 0 if context_ok else 1

    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    if os.path.isfile(_release_file):
        os.rename(_release_file, _release_file + '-' + mytime)

    # Download release file using subprocess instead of os.system
    subprocess.run(
        ['wget', '-q', '-O', 'release.file',
         f'https://main.myodoo.de/get_csv_file/{_accesscode}'],
        check=True
    )

    while not os.path.isfile(_release_file):
        time.sleep(0.1)

    if os.stat(_release_file).st_size != 0:
        with io.open(_release_file, 'r', encoding="utf8") as csvfile:
            _reader = csv.reader(csvfile, delimiter=",")
            _count = 1
            for _row in _reader:
                _column = _row[0].replace(' ', '')
                if _count == 1:
                    _url = _column
                elif _count == 2:
                    if _column != '':
                        update_dockerfile(_column)
                    else:
                        print('No Dockerimages defined!')
                else:
                    continue
                _count += 1

        print('Dockerfile image changed')
    else:
        print('No valid release file :(')

    print('Cleanup and finished!')
    return 0 if context_ok else 1


if __name__ == "__main__":
    sys.exit(main())
