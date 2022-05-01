#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank inkl. FileStore unter Docker durchgeführt
# With this script you can backup odoo db on postgresql incl. filestore under Docker
# Version 1.0.2
# Date 01.05.2022
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
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
#
##############################################################################
import os
import time
import shutil
import glob
from datetime import datetime, timedelta


def cleanup_backups(_cleanup_path, _cutoff_days):
    _files = os.listdir(_cleanup_path + "/")
    for _xfile in _files:
        if os.path.isfile(_cleanup_path + "/" + _xfile):
            t = os.stat(_cleanup_path + "/" + _xfile)
            c = t.st_ctime
            # delete file if older than 2 weeks
            if c < _cutoff_days:
                print("remove: " + _cleanup_path + "/" + _xfile)
                os.remove(_cleanup_path + "/" + _xfile)


_LOGS_PATH = '/var/log/nginx/'
_yesterday_datetime = datetime.now() - timedelta(days=1)
_yesterday_date = _yesterday_datetime.strftime('%Y-%m-%d')
_mystoretime = 7

_files = glob.glob(_LOGS_PATH + '*.log')
for i in range(len(_files)):
   shutil.move(_files[i], _files[i] + _yesterday_date +'.bak')

# run by crontab
# removes any files in mybackuppath older than 7 days or mystoretime

now = time.time()
_cutoff = now - (float(_mystoretime) * 86400)

# remove docker backups
os.system('systemctl stop nginx')
cleanup_backups(_LOGS_PATH, _cutoff)
os.system('sudo touch /var/cache/ngx_pagespeed/cache.flush')
os.system('echo "nginx start"')
os.system('systemctl start nginx')
os.system('systemctl status nginx')
print('Cleanup done!')