#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Version 3.3.0
# Date 17.03.2026
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
import re
import subprocess
import time
import datetime
import platform

_access_file = 'release.txt'
_release_file = 'release.file'

# Validation pattern for Docker image references (e.g. myodoo/prepare-v19:25.12.08-3.12.12)
_DOCKER_IMAGE_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9_.-]+$')

if platform.system() == 'Darwin':
    _sed_inplace = ["-i", ""]
else:
    _sed_inplace = ["-i"]


def update_dockerfile(image_ref: str) -> None:
    """Update Dockerfile FROM line and date using subprocess instead of os.system."""
    if not _DOCKER_IMAGE_PATTERN.match(image_ref):
        print(f'ERROR: Invalid Docker image reference: {image_ref}')
        print('Expected format: registry/image:tag (e.g. myodoo/prepare-v19:25.12.08-3.12.12)')
        return

    current_date = datetime.datetime.now().strftime('%d.%m.%Y')

    # Update FROM line
    sed_from_cmd = ["sed"] + _sed_inplace + [f'1s|.*|FROM {image_ref}|', "Dockerfile"]
    print(f'dockerimage: {image_ref}')
    subprocess.run(sed_from_cmd, check=True)

    # Update date line
    sed_date_cmd = ["sed"] + _sed_inplace + [f'4s|# Date.*|# Date {current_date}|', "Dockerfile"]
    subprocess.run(sed_date_cmd, check=True)


if __file__:
    if not __import__('os').path.isfile(_access_file):
        print('*********************************************')
        print('*               E R R O R                   *')
        print('*  NO file named access_myodoo.txt found!!  *')
        print('*********************************************')
    else:
        import os
        _accesscode = open(_access_file).readline().rstrip()
        if _accesscode == "":
            print('Not valid accesscode :(')
        else:
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
