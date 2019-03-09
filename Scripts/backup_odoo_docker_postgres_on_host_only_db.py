#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank ohne FileStore unter Docker durchgeführt
# With this script you can backup odoo db on postgresql  without filestore under Docker
# Version 1.1.0
# Date 08.03.2019
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
#DATABASENAME,DB_USER,DB_PASSWORD,MYODOO-CONTAINERNAME
fname_backup = 'docker2backup.csv'
reader1 = csv.reader(open(fname_backup, 'rb'))
mybasepath = os.getcwd()
mybackuppath = mybasepath + "/backups-docker"
if not os.path.exists(mybackuppath):
    os.mkdir(mybackuppath)
mynginxpath = mybasepath + "/backups-nginx"
if not os.path.exists(mynginxpath):
    os.mkdir(mynginxpath)

print mybackuppath

for row in reader1:
    mydb = row[0]
    if (not(row)):
        continue
    elif (mydb.startswith('#')) or (mydb == '') or (mydb == None):
        # Kommentarzeile
        continue
    my_db_user = row[1]
    my_db_password = row[2]
    mydatacontainer = row[3]
    print 'Database Name:' + mydb + '\nDatabase User:' + my_db_user + '\nDatabase Password:' + my_db_password + '\nMyOdooContainerName:' + mydatacontainer
    mybackupfolder = mybackuppath + '/' + mydb
    if not os.path.exists(mybackupfolder):
        os.mkdir(mybackupfolder)
    os.system('pg_dump --dbname=postgresql://'+my_db_user+':'+my_db_password+'@127.0.0.1:5432/' + mydb + ' > ' + mybackupfolder + '/dump.sql')
    filestorepath = '/opt/odoo/data/filestore/'
    os.system('mkdir ' + mybackupfolder + '/'+mydb)
    #os.system('docker cp ' + mydatacontainer + ':/opt/odoo/data/filestore/' + mydb + ' ' + mybackupfolder + '/')
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.rename(mybackupfolder + '/' + mydb, mybackupfolder + '/filestore')
    zip_dir(mybackupfolder, mybackuppath + '/' + mydatacontainer + '_dockerbackup_' + mytime + '.zip')
    os.system('rm -r ' + mybackupfolder)
    print 'Backup is done ' + mydatacontainer

# backup nginx-conf
if os.path.exists('/etc/nginx/conf.d/'):
    if not os.path.exists(mynginxpath):
        os.mkdir(mynginxpath)
    ts = time.time()
    mytime=datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r '+mynginxpath+'/nginx-confs_'+mytime+'.zip /etc/nginx/conf.d/')

# backup letsencrypt
if os.path.exists('/etc/letsencrypt/live/'):
    if not os.path.exists(mynginxpath):
        os.mkdir(mynginxpath)
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    os.system('zip -r ' + mynginxpath + '/letsencrypt_' + mytime + '.zip /etc/letsencrypt/live/')

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

# removes any files in mynginxpath older than 14 days
files = os.listdir(mynginxpath + "/")
for xfile in files:
    if os.path.isfile(mynginxpath + "/" + xfile):
        t = os.stat(mynginxpath + "/" + xfile)
        c = t.st_ctime
        
        # delete file if older than 2 weeks
        if c < cutoff:
            print "remove: " + mynginxpath + "/" + xfile
            os.remove(mynginxpath + "/" + xfile)

print 'Start rsync'
# csv format
# rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/
fname_rsync = 'rsync_targets.csv'
if os.path.isfile(fname_rsync):
    reader2 = csv.reader(open(fname_rsync, 'rb'))
    for row in reader2:
        if (not(row)):
            continue
        elif (row[0].startswith('#')):
            continue
        else:
            os.system(row[0])

print 'Backup done!'