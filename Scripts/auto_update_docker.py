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
import time

# csv format - separator ","
# update/noupdate,myodoo_containername,databasename,port,path2Dockfile,postgresql_containername,Docker_image_name
fname = 'containers2update.csv'
reader = csv.reader(open(fname, 'rb'))
mybasepath = os.getcwd()
myupdatepath=mybasepath + "/docker-update"
print myupdatepath

for row in reader:
	myupdate = row[0]
	myodoocontainer = row[1]
	mydb = row[2]
	myport = row[3]
	mypath = row[4]
	mydbcontainer = row[5]
	myimage = row[6]
	if myupdate=="update":
		myupdatepath=mybasepath + "/docker-update-"+mydb
		print 'MyOdoo Container:'+myodoocontainer+'\nDatabase Name:'+mydb+'\nPort:'+myport
		print 'Path:'+mypath+'\nDB Container:'+mydbcontainer+'\nImage:'+myimage
		filestorepath='/opt/odoo/data/filestore/'
		os.system('mkdir '+myupdatepath)
		os.system('docker cp '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb+' '+myupdatepath)
		print 'Filestore saved...'
		print myodoocontainer+' will be stop...'
		os.system('docker stop '+myodoocontainer)
		print myodoocontainer+' stopped...'
		os.system('docker rm '+myodoocontainer)
		print myodoocontainer+' removed...'
		os.system('docker rmi '+myimage+':latest')
		print myimage+' removed...'
		print myimage+' start building..'
		os.chdir(mypath)
		os.system('docker build -t '+myimage+' .')
		print myodoocontainer+' start updating...'
		os.system('docker run -it --rm -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' update -d '+mydb)
		print myodoocontainer+' starting...'
		os.system('docker run -d -p '+myport+':8069 --name="'+myodoocontainer+'" --link '+mydbcontainer+':db '+myimage+' start')
		print myodoocontainer+' started...'
		os.system('docker cp '+myupdatepath+'/'+mydb+' '+myodoocontainer+':/opt/odoo/data/filestore/'+mydb)
		print 'Filestore restored...'
		print myodoocontainer+' restarting...'
		os.system('docker restart '+myodoocontainer)
		print myodoocontainer+' restarted...'
		if os.path.isfile(mypath+"load_translation.py"):
			print 'Translation loading...'
			time.sleep(10)
			os.system("python "+mypath+"load_translation.py")
			print 'Translation loaded...'
		print myodoocontainer+' restarting...'
		os.system('docker restart '+myodoocontainer)
		print myodoocontainer+' restarted...'
		os.system('rm -r '+myupdatepath)
		print 'Update is done '+mydb
	else:
		print 'NO update for '+mydb
