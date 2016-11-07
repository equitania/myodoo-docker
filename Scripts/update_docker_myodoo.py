#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Update einer Odoo Datenbank unter Docker durchgeführt
# With this script you can update odoo db on postgresql under Docker
# Version 1.1.1
# Date 07.11.2016
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
import csv
import os
import time

# csv format - separator ","
# myodoo_containername,databasename,port,path2Dockfile,docker_image_name,postgresql_username,postgresql_userpassword,hostname/ip
fname = 'docker2update_pg.csv'
reader = csv.reader(open(fname, 'rb'))
mybasepath = os.getcwd()

for row in reader:
    myodoocontainer = row[0]
    if myodoocontainer.startswith('#'):
        # Kommentarzeile
        continue
    mydb = row[1]
    myport = row[2]
    mypath = row[3]
    myimage = row[4]
    mydbuser = row[5]
    mydbpassword = row[6]
    mydbhost = row[7]
    print 'MyOdoo Container:' + myodoocontainer + '\nDatabase Name:' + mydb + '\nPort:' + myport
    print 'Path:' + mypath + '\nImage:' + myimage
    os.system('docker cp ' + myodoocontainer + ':/opt/odoo/data/filestore/' + mydb + ' ' + mypath + mydb)
    print 'Filestore saved...'
    print myodoocontainer + ' will be stop...'
    os.system('docker stop ' + myodoocontainer)
    print myodoocontainer + ' stopped...'
    os.system('docker rm ' + myodoocontainer)
    print myodoocontainer + ' removed...'
    os.system('docker rmi ' + myimage + ':latest')
    print myimage + ' removed...'
    print myimage + ' start building..'
    os.chdir(mypath)
    if os.path.isfile(mypath + "getMyOdooRelease.sh"):
        print 'Get latest release loading...'
        os.system('/bin/bash getMyOdooRelease.sh')
    os.system('docker build -t ' + myimage + ' .')
    print myodoocontainer + ' start updating...'
    os.system(
        'docker run -it --rm -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' update --database=' + mydb + ' --db_user=' + mydbuser + ' --db_password=' + mydbpassword + ' --db_host=' + mydbhost)
    print myodoocontainer + ' starting...'
    os.system('docker run -d -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' start')
    if os.path.isfile(mypath + "load_translation.py"):
        print 'Translation loading...'
        time.sleep(10)
        os.system("python " + mypath + "load_translation.py")
        print 'Translation loaded...'
    if os.path.isfile(mypath + "set_custom_translations.py"):
        print 'Translation bugfixes...'
        os.system("python " + mypath + "set_custom_translations.py")
        print 'Translation bugfixed...'
    print myodoocontainer + ' restarting...'
    os.system('docker cp ' + myodoocontainer + ':/opt/odoo/data/filestore/' + mydb + ' ' + mypath + mydb)
    os.system('docker stop ' + myodoocontainer)
    os.system('docker rm ' + myodoocontainer)
    os.system(
        'docker run -d --restart=always -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' start -u eq_website_customerportal')
    os.system('docker cp ' + mypath + mydb + ' ' + myodoocontainer + ':/opt/odoo/data/filestore/' + mydb)
    print myodoocontainer + ' restarted...'
    os.system('rm -r ' + mypath + mydb)
    print 'Update is done ' + mydb
