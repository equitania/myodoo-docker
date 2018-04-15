#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Update einer Odoo Datenbank unter Docker durchgeführt
# With this script you can update odoo db on postgresql under Docker
# Version 2.0.0
# Date 15.04.2018
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
import sys

# csv format - separator ","
# myodoo_containername,databasename,port,path2Dockfile,docker_image_name,postgresql_username,postgresql_userpassword,hostname/ip,volumen,kommado
fname = 'docker2update.csv'
reader = csv.reader(open(fname, 'rb'))
mybasepath = os.getcwd()

for row in reader:
    mydb = ""
    myport = ""
    mypath = ""
    myimage = ""
    mydbuser = ""
    mydbpassword = ""
    mydbhost = ""
    myvolumen = ""
    myupdate = ""

    # Name des Docker Containers
    myodoocontainer = row[0]
    if myodoocontainer.startswith('#'):
        # Kommentarzeile
        continue
    # Name des Datenbank
    mydb = row[1]
    # Port nach außen
    myport = row[2]
    # Lokaler Pfad zum Dockerfile
    mypath = row[3]
    # Name des Images, das gebildet werden soll
    myimage = row[4]
    # Name des Datenbankbenutzers (Postgres) 
    mydbuser = row[5]
    # Passwort des Datenbankbenutzers (Postgres) 
    mydbpassword = row[6]
    # IP 
    mydbhost = row[7]
    # Dieser Parameter das Speichern des Filestores auf dem Host
    try:
        myvolumen = row[8]
    except:
        print("Volumen-Parameter ist nicht vorhanden!")
    # Dieser Parameter kann für Update mit "-u modulname" oder Installationen "-i modulname" verwendet werden
    try:
        myupdate = row[9]
    except:
        print("Update-Spalte ist nicht vorhanden!")
    print 'MyOdoo Container:' + myodoocontainer + '\nDatabase Name:' + mydb + '\nPort:' + myport
    print 'Path:' + mypath + '\nImage:' + myimage + '\n'
    print 'Volumen:' + myvolumen + '\n'
    print 'Post Update:' + myupdate
    if myvolumen != "":
        os.system('mkdir ' + mypath + mydb)
        os.system('docker cp ' + myodoocontainer + ':/opt/odoo/data/filestore/' + mydb + ' ' + mypath)
        print 'Filestore saved...'
    os.chdir(mypath)
    if os.path.isfile(mypath + 'getMyOdooRelease.sh'):
        print 'Get latest release loading...'
        os.system('/bin/bash getMyOdooRelease.sh')
    print myodoocontainer + ' will be stop...'
    os.system('docker stop ' + myodoocontainer)
    print myodoocontainer + ' stopped...'
    os.system('docker rm ' + myodoocontainer)
    print myodoocontainer + ' removed...'
    os.system('docker rmi ' + myimage + ':latest')
    print myimage + ' removed...'
    print myimage + ' start building..'
    os.system('docker build -t ' + myimage + ' .')
    print myodoocontainer + ' start updating...'
    os.system('docker run -it --rm -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' update --database=' + mydb + ' --db_user=' + mydbuser + ' --db_password=' + mydbpassword + ' --db_host=' + mydbhost)
    print myodoocontainer + ' starting...'
    os.system('docker run -d -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' start')
    if os.path.isfile(mypath + 'load_translation.py'):
        print 'Translation loading...'
        time.sleep(60)
        os.system("python " + mypath + 'load_translation.py')
        print 'Translation loaded...'
    if os.path.isfile(mypath + 'set_custom_translation.py'):
        print 'Translation bugfixes...'
        os.system("python " + mypath + 'set_custom_translation.py')
        print 'Translation bugfixed...'
    print myodoocontainer + ' restarting...'
    os.system('docker stop ' + myodoocontainer)
    os.system('docker rm ' + myodoocontainer)
    if myupdate != "":
        print 'Post update wird durchgeführt.'
    print 'docker run -d --restart=always -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' start ' + myupdate
    os.system('docker run -d --restart=always -p ' + myport + ':8069 --name="' + myodoocontainer + '" ' + myimage + ' start ' + myupdate)
    print myodoocontainer + ' restarted...'
    if os.path.exists(mypath + mydb + '.bak'):
        os.system('rm -r ' + mypath + mydb + '.bak')
    os.system('mv ' + mypath + mydb + ' ' + mypath + mydb + '.bak')
    print 'Update is done ' + mydb