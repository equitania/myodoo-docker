#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird mittels dem Release Manager ein neuer Server gebaut
# Version 1.1.0
# Date 07.10.2019
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

import os, csv, time

_build_path = '/opt/odoo'
_release_file = 'release.file'

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
                        os.system('wget -qq ' + _url + '/' + _column)
                        os.system('mkdir -p odoo-server/addons')
                        while not os.path.isfile(_column):
                            time.sleep(0.1)
                        os.system('unzip -q ' + _column + ' -d odoo-server')
                        print('kernel: ' + _column + ' loaded and installed..')
                else:
                    if _column.find('.zip') is not -1:
                        os.system('wget -qq ' + _url + '/' + _column)
                        while not os.path.isfile(_column):
                            time.sleep(0.1)
                        os.system('unzip -q ' + _column + ' -d odoo-server/addons')
                        print('file: ' + _column + ' loaded and installed..')
                    else:
                        continue
                _count += 1
    else:
        print('No valid release file :(')
        exit()
    print('Build finished!')
    os.system('rm -f *.zip')
    #os.system('rm -f release.file')
    print('Cleanup and finished!')
else:
    print('*********************************************')
    print('*               E R R O R                   *')
    print('*    NO file named release.file found!!     *')
    print('*********************************************')
