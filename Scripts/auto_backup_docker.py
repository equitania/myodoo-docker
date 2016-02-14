#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank inkl. FileStore unter Docker durchgeführt
# With this script you can backup odoo db on postgresql incl. filestore under Docker
# Version 1.0.1
# Date 14.12.2015
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
import sys
import zipfile
import datetime, time
from subprocess import call

def zip_dir(dirpath, zippath):
	fzip = zipfile.ZipFile(zippath, 'w', zipfile.ZIP_DEFLATED)
	basedir = os.path.dirname(dirpath) + '/'
	for root, dirs, files in os.walk(dirpath):
		if os.path.basename(root)[0] == '.':
			continue #skip hidden directories
		dirname = root.replace(basedir, '')
		for f in files:
			if f[-1] == '~' or (f[0] == '.' and f != '.htaccess'):
				continue
			fzip.write(root + '/' + f, dirname + '/' + f)
	fzip.close()
	return;

# csv format - separator ","
# databasename,postgresql_containername,myodoo_containername
fname_backup = 'containers2backup.csv'
reader1 = csv.reader(open(fname_backup, 'rb'))
mybasepath = os.getcwd()
mybackuppath=mybasepath + "/docker-backups"
print mybackuppath

for row in reader1:
	mydb = row[0]
	if mydb.startswith('#'):
		# Kommentarzeile
		continue
	mysqlcontainer = row[1]
	mydatacontainer = row[2]
	print 'Database Name:'+mydb+'\nDatabaseContainerName:'+mysqlcontainer+'\nMyOdooContainerName:'+mydatacontainer
	mybackupfolder=mybackuppath+'/'+mydb
	os.mkdir(mybackupfolder)
	os.system('docker exec -i '+mysqlcontainer+' pg_dump -U odoo '+mydb+' > '+mybackupfolder+'/dump.sql')
	filestorepath='/opt/odoo/data/filestore/'
	os.system('docker cp '+mydatacontainer+':/opt/odoo/data/filestore/'+mydb+' '+mybackupfolder+'/')
	ts = time.time()
	mytime=datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
	os.rename(mybackupfolder+'/'+mydb,mybackupfolder+'/filestore')
	zip_dir(mybackupfolder,mybackuppath+'/'+mydatacontainer+'_dockerbackup_'+mytime+'.zip')
	os.system('rm -r '+mybackupfolder)
	print 'Backup is done ' + mydatacontainer

# backup nginx-conf
os.mkdir('/root/nginx-backups/')
ts = time.time()
mytime=datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
os.system('zip -r /root/nginx-backups/nginx-confs_'+mytime+'.zip /etc/nginx/conf.d/')

# run by crontab
# removes any files in mybackuppath older than 14 days

now = time.time()
cutoff = now - (14 * 86400)

files = os.listdir(mybackuppath+"/")
for xfile in files:
	if os.path.isfile(mybackuppath + "/" + xfile ):
		t = os.stat( mybackuppath + "/" + xfile )
		c = t.st_ctime

		# delete file if older than 2 weeks
		if c < cutoff:
			print "remove: " + mybackuppath + "/" + xfile
			os.remove(mybackuppath + "/" + xfile)

print 'Start rsync'
# csv format
# rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/
fname_rsync = 'rsync_targets.csv'
if os.path.isfile(fname_rsync):
	reader2 = csv.reader(open(fname_rsync, 'rb'))
	for row in reader2:
		os.system(row[0])
