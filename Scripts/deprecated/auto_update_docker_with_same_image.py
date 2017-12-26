#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Update einer Odoo Datenbank unter Docker durchgeführt
# With this script you can update odoo db on postgresql under Docker
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

# csv format - separator ","
# myodoo_containername,databasename,port,path2Dockfile,postgresql_containername,Docker_image_name
fname = 'containers2update_with_same_image.csv'
reader1 = csv.reader(open(fname, 'rb'))
reader2 = csv.reader(open(fname, 'rb'))
reader3 = csv.reader(open(fname, 'rb'))
reader4 = csv.reader(open(fname, 'rb'))
mybasepath = os.getcwd()
myupdatepath=mybasepath + "/docker-update"
print myupdatepath

for row in reader1:
	myodoocontainer = row[0]
	mydb = row[1]
	myport = row[2]
	mypath = row[3]
	mydbcontainer = row[4]
	myimage = row[5]
	myupdatepath=mybasepath + "/docker-update-"+myodoocontainer
	print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
	print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
	filestorepath='/opt/odoo/data/filestore/'
	os.system('mkdir '+myupdatepath)
	os.system('docker cp '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb+' '+myupdatepath)
	print 'Filestore saved...'

# Stop and remove containers
for row in reader2:
	myodoocontainer = row[0]
	mydb = row[1]
	myport = row[2]
	mypath = row[3]
	mydbcontainer = row[4]
	myimage = row[5]
	print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
	print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
	print myodoocontainer+' will be stop...'
	os.system('docker stop '+myodoocontainer)
	print myodoocontainer+' stopped...'
	os.system('docker rm '+myodoocontainer)
	print myodoocontainer+' removed...'
	print 'Remove container is done '+mydb

# Remove and rebuild image
os.system('docker rmi '+myimage+':latest')
print myimage+' removed...'
print myimage+' start building..'
os.chdir(mypath)
os.system('docker build -t '+myimage+' .')


# Starting and update containers
for row in reader3:
	myodoocontainer = row[0]
	mydb = row[1]
	myport = row[2]
	mypath = row[3]
	mydbcontainer = row[4]
	myimage = row[5]
	myupdatepath=mybasepath + "/docker-update-"+myodoocontainer
	print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
	print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
	print myodoocontainer+' start updating...'
	os.system('docker run -it --rm -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' update -d '+mydb)
	print myodoocontainer+' starting...'
	os.system('docker run -d -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' start')
	print myodoocontainer+' started...'
	print 'Update is done '+mydb


# Restore Filestores
for row in reader4:
	myodoocontainer = row[0]
	mydb = row[1]
	myport = row[2]
	mypath = row[3]
	mydbcontainer = row[4]
	myimage = row[5]
	myupdatepath=mybasepath + "/docker-update-"+myodoocontainer
	print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
	print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
	filestorepath='/opt/odoo/data/filestore/'
	os.system('docker cp '+myupdatepath+'/'+mydb+' '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb)
	print 'Filestore restored...'
	print myodoocontainer+' restarting...'
	os.system('docker restart '+myodoocontainer)
	print myodoocontainer+' restarted...'
	os.system('rm -r '+myupdatepath)
	print 'Restore is done '+mydb
