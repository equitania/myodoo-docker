#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer PostgreSQL Datenbank
# With this script you can backup postgresql db
# Version 1.0.1
# Date 24.03.2019
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
import csv
import zipfile
import datetime, time
from os.path import expanduser

def zip_dir(dirpath, zippath):
    fzip = zipfile.ZipFile(zippath, 'w', zipfile.ZIP_DEFLATED, allowZip64 = True)
    basedir = os.path.dirname(dirpath) + '/'
    for root, dirs, files in os.walk(dirpath):
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
#DATABASENAME,DB_USER,DB_PASSWORD
_home = expanduser("~")
fname_backup = _home + '/backup_postgres_db.csv'
reader1 = csv.reader(open(fname_backup, 'rb'))
mybasepath = os.getcwd()
mybackuppath = mybasepath + "/backups-postgres"
if not os.path.exists(mybackuppath):
    os.mkdir(mybackuppath)

print mybackuppath

for row in reader1:
    mydb = row[0]
    if mydb.startswith('#'):
        # Kommentarzeile
        continue
    my_db_user = row[1]
    my_db_password = row[2]
    print 'Database Name:' + mydb + '\nDatabase User:' + my_db_user + '\nDatabase Password:' + my_db_password
    mybackupfolder = mybackuppath + '/' + mydb
    if not os.path.exists(mybackupfolder):
        os.mkdir(mybackupfolder)
    os.system('pg_dump --dbname=postgresql://'+my_db_user+':'+my_db_password+'@127.0.0.1:5432/' + mydb + ' > ' + mybackupfolder + '/' + mydb + '.sql')
    os.system('mkdir ' + mybackupfolder + '/' + mydb)
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    zip_dir(mybackupfolder, mybackuppath + '/' + mydb + '_postgres_backup_' + mytime + '.zip')
    os.system('rm -r ' + mybackupfolder)
    print 'Backup is done ' + mydb


# run by crontab
# removes any files in mybackuppath older than 14 days

now = time.time()
cutoff = now - (14 * 86400)

files = os.listdir(mybackuppath + "/")
for xfile in files:
    if os.path.isfile(mybackuppath + "/" + xfile):
        t = os.stat(mybackuppath + "/" + xfile)
        c = t.st_ctime
        
        # delete file if older than 2 weeks
        if c < cutoff:
            print "remove: " + mybackuppath + "/" + xfile
            os.remove(mybackuppath + "/" + xfile)


print 'Start rsync'
# csv format
# rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/
fname_rsync = 'rsync_targets_postgres.csv'
if os.path.isfile(fname_rsync):
    reader2 = csv.reader(open(fname_rsync, 'rb'))
    for row in reader2:
        os.system(row[0])
print 'Backup done!'
