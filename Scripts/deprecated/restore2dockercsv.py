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
import time

# csv format - separator ","
# myodoo_containername,databasename,port,path2Dockfile,postgresql_containername,Docker_image_name
fname = 'containers2restore.csv'
reader1 = csv.reader(open(fname, 'rb'))
mybasepath = os.getcwd()
myupdatepath=mybasepath + "/docker-update"
mybackuppath=mybasepath + "/docker-backups"
print myupdatepath
print mybackuppath

# Starting and update containers
for row in reader1:
	myodoocontainer = row[0]
	if myodoocontainer.startswith('#'):
		# Kommentarzeile
		continue
	mydb = row[1]
	myport = row[2]
	mypath = row[3]
	mydbcontainer = row[4]
	myimage = row[5]
	myupdatepath=mybasepath + "/docker-update-"+myodoocontainer
	print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
	print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
	print myodoocontainer+' start updating...'
	os.system('unzip '+mybackuppath+'/'+myodoocontainer+'_dockerbackup.zip')
	os.system('docker run -d -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo --name '+mydbcontainer+' postgres:9.4')
	print ' '
	time.sleep(10)
	print 'docker exec -i '+mydbcontainer+' createdb -U odoo -T template0 '+mydb
	os.system('docker exec -i '+mydbcontainer+' createdb -U odoo -T template0 '+mydb)
	print 'cat '+mydb+'/dump.sql'+' | docker exec -i '+mydbcontainer+' psql -U odoo -d '+mydb
	os.system('cat '+mydb+'/dump.sql'+' | docker exec -i '+mydbcontainer+' psql -U odoo -d '+mydb)
	print 'docker run -it --rm -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' update -d '+mydb
	os.system('docker run -it --rm -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' update -d '+mydb)
	print 'docker run -d -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' start'
	os.system('docker run -d -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' start')
	print myodoocontainer+' started...'
	print 'docker cp '+mydb+'/filestore/ '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb+'/'
	os.system('docker cp '+mydb+'/filestore/ '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb+'/')
	print 'docker exec -i '+myodoocontainer+' chown -R odoo:odoo /opt/odoo/data/'
	os.system('docker exec -i '+myodoocontainer+' chown -R odoo:odoo /opt/odoo/data/')
	print 'Filestore restored...'
	print myodoocontainer+' restarting...'
	os.system('docker restart '+myodoocontainer)
	print myodoocontainer+' restarted...'
	os.system('rm -r '+mydb+'/')
	print 'Restore is done '+mydb
