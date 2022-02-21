#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank inkl. FileStore unter Docker durchgeführt
# With this script you can backup odoo db on postgresql incl. filestore under Docker
# Version 3.1.0
# Date 21.02.2022
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
import io
import csv
import zipfile
import datetime, time
from os.path import expanduser

def zip_dir(_dir_path, _zip_path):
    fzip = zipfile.ZipFile(_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)
    basedir = os.path.dirname(_dir_path) + '/'
    for root, dirs, files in os.walk(_dir_path):
        if os.path.basename(root)[0] == '.':
            continue  # skip hidden directories
        dirname = root.replace(basedir, '')
        for f in files:
            if f[-1] == '~' or (f[0] == '.' and f != '.htaccess'):
                continue
            fzip.write(root + '/' + f, dirname + '/' + f)
    fzip.close()
    return;

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

# csv format - separator ","
# databasename,postgresql_containername,myodoo_containername,number_of_days
_mybasepath = expanduser("~")
_fname_backup = _mybasepath + '/container2backup.csv'
_fname_backup_path = _mybasepath + '/container2backup_path.csv'

if _fname_backup_path.exists():
    _mybackup_file  = open(_fname_backup_path, 'r', encoding="utf8")
    _mybackuppath = _mybackup_file.readline()
else:
    _mybackuppath = "/opt/backups"

print("Backup path: " + _mybackuppath)

if not os.path.exists(_mybackuppath):
    os.system("mkdir -p " + _mybackuppath)

_mynginxpath = _mybackuppath + "/nginx"
if not os.path.exists(_mynginxpath):
    os.mkdir(_mynginxpath)

_mydockerbuildpath = _mybackuppath + "/docker-builds"
if not os.path.exists(_mydockerbuildpath):
    os.mkdir(_mydockerbuildpath)

_mybackuppath = _mybackuppath + "/docker"
if not os.path.exists(_mybackuppath):
    os.mkdir(_mybackuppath)

print(_mybackuppath)

with io.open(_fname_backup, 'r', encoding="utf8") as csvfile:
    _reader = csv.reader(csvfile, delimiter=",")
    for row in _reader:
        _mydb = row[0]
        if (not(row)):
            continue
        elif (row[0].startswith('#')):
            continue
            # Kommentarzeile
        _mydbuser = row[1]
        _mysqlcontainer = row[2]
        _mydatacontainer = row[3]
        try:
            _mystoretime = row[4]
        except:
            _mystoretime = 14
        print('Database Name:' + _mydb + '\nDatabaseContainerName:' + _mysqlcontainer + '\nMyOdooContainerName:' + _mydatacontainer + '\nStoreTime:' + str(_mystoretime) + ' days')
        _mybackupfolder = _mybackuppath + '/' + _mydb
        if not os.path.exists(_mybackupfolder):
            os.mkdir(_mybackupfolder)
        os.system('docker exec -i ' + _mysqlcontainer + ' pg_dump -U ' + _mydbuser + ' ' + _mydb + ' > ' + _mybackupfolder + '/dump.sql')
        filestorepath = '/opt/odoo/data/filestore/'
        os.system('docker cp ' + _mydatacontainer + ':/opt/odoo/data/filestore/' + _mydb + ' ' + _mybackupfolder + '/')
        ts = time.time()
        mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
        #os.rename(mybackupfolder + '/' + mydb, mybackupfolder + '/filestore')
        zip_dir(_mybackupfolder, _mybackuppath + '/' + _mydatacontainer + '_dockerbackup_' + mytime + '.zip')
        os.system('rm -r ' + _mybackupfolder)
        print('Backup is done ' + _mydatacontainer)

# backup nginx-conf
if os.path.exists('/etc/nginx/conf.d/'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + _mynginxpath + '/nginx-confs_' + mytime + '.zip /etc/nginx/')

# backup letsencrypt
if os.path.exists('/etc/letsencrypt/live/'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + _mynginxpath + '/letsencrypt_' + mytime + '.zip /etc/letsencrypt/live/')

# backup docker-builds
if os.path.exists('/root/docker-builds'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + _mydockerbuildpath + '/docker-builds' + mytime + '.zip /root/docker-builds/')

# run by crontab
# removes any files in mybackuppath older than 14 days or mystoretime

now = time.time()
_cutoff = now - (float(_mystoretime) * 86400)

# remove docker backups
cleanup_backups(_mybackuppath, _cutoff)

# removes any files in mynginxpath older than 14 days
cleanup_backups(_mynginxpath, _cutoff)

# removes any files in mydockerbuildpath older than 14 days
cleanup_backups(_mydockerbuildpath, _cutoff)

# csv format
# rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/
fname_rsync = _mybasepath + '/rsync_targets.csv'
print('Start rsync: ' + fname_rsync)
if os.path.isfile(fname_rsync):
    with io.open(fname_rsync, 'r', encoding="utf8") as csvfile:
        _reader_sync = csv.reader(csvfile, delimiter=",")
        for row in _reader_sync:
            if (not(row)):
                continue
            elif (row[0].startswith('#')):
                continue
            else:
                os.system(row[0])
print('Backup done!')
