#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank inkl. FileStore unter Docker durchgeführt
# With this script you can backup odoo db on postgresql incl. filestore under Docker
# Version 3.0.1
# Date 26.06.2020
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


# csv format - separator ","
# databasename,postgresql_containername,myodoo_containername,number_of_days
mybasepath = expanduser("~")
mybackuppath = "/opt/backups"
fname_backup = mybasepath + '/container2backup.csv'
mynginxpath = mybackuppath + "/nginx"
if not os.path.exists(mynginxpath):
    os.mkdir(mynginxpath)
mybackuppath = mybackuppath + "/docker"
if not os.path.exists(mybackuppath):
    os.mkdir(mybackuppath)

print(mybackuppath)

with io.open(fname_backup, 'r', encoding="utf8") as csvfile:
    _reader = csv.reader(csvfile, delimiter=",")
    for row in _reader:
        mydb = row[0]
        if (not(row)):
            continue
        elif (row[0].startswith('#')):
            continue
            # Kommentarzeile
        mydbuser = row[1]
        mysqlcontainer = row[2]
        mydatacontainer = row[3]
        try:
            mystoretime = row[4]
        except:
            mystoretime = 14
        print('Database Name:' + mydb + '\nDatabaseContainerName:' + mysqlcontainer + '\nMyOdooContainerName:' + mydatacontainer + '\nStoreTime:' + str(mystoretime) + ' days')
        mybackupfolder = mybackuppath + '/' + mydb
        if not os.path.exists(mybackupfolder):
            os.mkdir(mybackupfolder)
        os.system('docker exec -i ' + mysqlcontainer + ' pg_dump -U ' + mydbuser + ' ' + mydb + ' > ' + mybackupfolder + '/dump.sql')
        filestorepath = '/opt/odoo/data/filestore/'
        os.system('docker cp ' + mydatacontainer + ':/opt/odoo/data/filestore/' + mydb + ' ' + mybackupfolder + '/')
        ts = time.time()
        mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
        #os.rename(mybackupfolder + '/' + mydb, mybackupfolder + '/filestore')
        zip_dir(mybackupfolder, mybackuppath + '/' + mydatacontainer + '_dockerbackup_' + mytime + '.zip')
        os.system('rm -r ' + mybackupfolder)
        print('Backup is done ' + mydatacontainer)

# backup nginx-conf
if os.path.exists('/etc/nginx/conf.d/'):
    if not os.path.exists(mynginxpath):
        os.mkdir(mynginxpath)
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + mynginxpath + '/nginx-confs_' + mytime + '.zip /etc/nginx/')

# backup letsencrypt
if os.path.exists('/etc/letsencrypt/live/'):
    if not os.path.exists(mynginxpath):
        os.mkdir(mynginxpath)
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + mynginxpath + '/letsencrypt_' + mytime + '.zip /etc/letsencrypt/live/')

# run by crontab
# removes any files in mybackuppath older than 14 days or mystoretime

now = time.time()
cutoff = now - (float(mystoretime) * 86400)

files = os.listdir(mybackuppath + "/")
for xfile in files:
    if os.path.isfile(mybackuppath + "/" + xfile):
        t = os.stat(mybackuppath + "/" + xfile)
        c = t.st_ctime

        # delete file if older than 2 weeks
        if c < cutoff:
            print("remove: " + mybackuppath + "/" + xfile)
            os.remove(mybackuppath + "/" + xfile)

# removes any files in mynginxpath older than 14 days
files = os.listdir(mynginxpath + "/")
for xfile in files:
    if os.path.isfile(mynginxpath + "/" + xfile):
        t = os.stat(mynginxpath + "/" + xfile)
        c = t.st_ctime

        # delete file if older than 2 weeks
        if c < cutoff:
            print("remove: " + mynginxpath + "/" + xfile)
            os.remove(mynginxpath + "/" + xfile)

# csv format
# rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/
fname_rsync = mybasepath + '/rsync_targets.csv'
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
