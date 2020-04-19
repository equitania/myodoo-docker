#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Backup einer Odoo Datenbank inkl. FileStore mittels XMLRPC durchgeführt
# With this script you can backup odoo db on postgresql incl. filestore with XMLRPC
# Version 1.0.2
# Date 21.03.2016
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
import datetime, time
import xmlrpclib
import base64

# csv format - separator ","
#DBNAME,DBADMINPASSWORD,URL
fname_backup = 'docker2bakxmlrpc.csv'
reader1 = csv.reader(open(fname_backup, 'rb'))
mybasepath = os.getcwd()
mybackuppath=mybasepath + "/docker-backups"
if not os.path.exists(mybackuppath):
	os.mkdir(mybackuppath)
mynginxpath=mybasepath + "/nginx-backups"
if not os.path.exists(mynginxpath):
	os.mkdir(mynginxpath)

print mybackuppath

for row in reader1:
	mydb = row[0]
	if mydb.startswith('#'):
		# Kommentarzeile
		continue
	mydbpwd = row[1]
	mybaseurl = row[2]
	print 'Database Name:'+mydb+'\nDBAdmin Password:'+mydbpwd+'\nContainer URL:'+mybaseurl
	sock = xmlrpclib.ServerProxy(mybaseurl + "/xmlrpc/db")
	ts = time.time()
	mytime=datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
	file_path = mybackuppath+'/'+mydb+'_odoo_backup_'+mytime+'.zip'
	try:
		backup_db_file = open(file_path, 'wb')
		backup_db_file.write(base64.b64decode(sock.dump(mydbpwd, mydb)))
		backup_db_file.close()
		print 'Backup is done ' + mydb
	except:
		print 'Backup NOT possible ' + mydb
		continue	

# backup nginx-conf
if not os.path.exists(mynginxpath):
	os.mkdir(mynginxpath)
ts = time.time()
mytime=datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
os.system('zip -r '+mynginxpath+'/nginx-confs_'+mytime+'.zip /etc/nginx/conf.d/')

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

# removes any files in mynginxpath older than 14 days
files = os.listdir(mynginxpath+"/")
for xfile in files:
	if os.path.isfile(mynginxpath + "/" + xfile ):
		t = os.stat( mynginxpath + "/" + xfile )
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
		os.system(row[0])
print 'Backup done!'
