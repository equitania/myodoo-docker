#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript wird mittels dem Release Manager ein neuer Server gebaut
# Version 2.0.0
# Date 09.10.2023
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

import os
import csv
import urllib3

_build_path = '/opt/odoo'
_release_file = 'release.file'

# Create an urllib3.PoolManager instance
http = urllib3.PoolManager()

if os.path.isfile(_release_file):
    print('Starting with build at ' + _build_path)
    os.chdir(_build_path)
    # Wenn Releasefile gefüllt ist, beginnt der Buildprozess
    if os.stat(_release_file).st_size != 0:
        with open(_release_file, encoding="utf8") as csvfile:
            _reader = csv.reader(csvfile, delimiter=",")
            _count = 1
            for _row in _reader:
                _column = _row[0]
                _column = _column.replace(' ', '')
                if _count == 1:
                    print('url: ' + _column)
                    _url = _column
                    if _url == 'False':
                        print('url is missing .. stop!')
                        exit()
                elif _count == 2:
                    print('dockerimage: ' + _column)
                elif _count == 3:
                    if _column == 'False':
                        print('kernel is missing .. stop!')
                        exit()
                    else:
                        os.system('mkdir -p odoo-server/addons')
                        _zip_url = _url + '/' + _column
                        # Send an HTTP GET request to the URL
                        response = http.request('GET', _zip_url)
                        # Check if the request was successful (status code 200)
                        if response.status == 200:
                            # Open the local file in binary write mode and write the downloaded content to it
                            with open(_column, 'wb') as f:
                                f.write(response.data)
                            print(f"File downloaded successfully to {_column}")
                        else:
                            print(f"Failed to download file. Status code: {response.status}")
                        os.system('unzip -q ' + _column + ' -d odoo-server')
                        print('kernel: ' + _column + ' loaded and installed..')
                else:
                    # Get and extract modules
                    if _column.find('.zip') != -1:
                        _zip_url = _url + '/' + _column
                        # Send an HTTP GET request to the URL
                        response = http.request('GET', _zip_url)
                        # Check if the request was successful (status code 200)
                        if response.status == 200:
                            # Open the local file in binary write mode and write the downloaded content to it
                            with open(_column, 'wb') as f:
                                f.write(response.data)
                            print(f"File downloaded successfully to {_column}")
                            os.system('unzip -q ' + _column + ' -d odoo-server/addons')
                            print('file: ' + _column + ' loaded and installed..')
                        else:
                            print(f"Failed to download file. Status code: {response.status}")
                    else:
                        continue
                _count += 1
        if os.path.exists('custom_modules.zip'):
            os.system('unzip -q custom_modules.zip -d odoo-server/addons')
            print('file: custom_modules.zip loaded and installed..')
    else:
        print('No valid release file :(')
        exit()
    print('Build finished!')
    os.system('rm -f *.zip')
    os.system('rm -f build_myodoo.py')
    os.system('rm -f release.file')
    print('Cleanup and finished!')
else:
    print('*********************************************')
    print('*               E R R O R                   *')
    print('*    NO file named release.file found!!     *')
    print('*********************************************')