#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript wird ein Update einer Odoo Datenbank unter Docker durchgeführt
# With this script you can update odoo db on postgresql under Docker
# Version 2.4.3
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
import csv
import os
import time
from os.path import expanduser

# csv format - separator "," [M]odules or [F]ull update,containername,databasename,port,longpollingport,
# path2Dockfile,docker_image_name,postgresql_username,postgresql_userpassword,hostname/ip,volumen,update 
_home = expanduser("~")
_fname = _home + '/docker2update.csv'
_reader = csv.reader(open(_fname, 'rb'))
_mybasepath = os.getcwd()

for _row in _reader:
    _mytype = ""  # type: str
    _mydelaytime = 0  # type: int
    _mycontainer = ""  # type: str
    _mydb = ""  # type: str
    _myport = ""  # type: str
    _mypollport = ""  # type: str
    _mypath = ""  # type: str
    _myimage = ""  # type: str
    _mydbuser = ""  # type: str
    _mydbpassword = ""  # type: str
    _mydbhost = ""  # type: str
    _myvolumen = ""  # type: str
    _myupdate = ""  # type: str

    # name of docker containers
    _mytype = _row[0]
    if (not(_row)):
        continue
    elif (_mytype.startswith('#')):
        continue
        # Kommentarzeile
    # delay time before restart
    _mydelaytime = int(_row[1])
    if _mydelaytime == 0:
        _mydelaytime = 10
    # name of container
    _mycontainer = _row[2]
    # name of database
    _mydb = _row[3]
    # odoo outside port inside 8069
    _myport = _row[4]
    # odoo outside longpolling_port inside 8072
    _mypollport = _row[5]
    # local path Dockerfile
    _mypath = _row[6]
    # name of local Docker image
    _myimage = _row[7]
    # user Postgres db
    _mydbuser = _row[8]
    # password Postgres db
    _mydbpassword = _row[9]
    # host name or ip postgres server
    _mydbhost = _row[10]
    # extended docker parameter like --volume
    try:
        _myvolumen = _row[11]
    except:
        print("No volume paramter was set!")
    # additional install or update command "-u modulname" or Installationen "-i modulname"
    try:
        _myupdate = _row[12]
    except:
        print("No update or install command!")
    # Missing path to Dockerfile
    if not os.path.isdir(_mypath):
        print("Docker path isn't correct!")
        continue
    # Update mode
    if _mytype == "F":
        print("Full update")
    elif _mytype == "M":
        print("Only module copy in container")
    else:
        print("Missing update mode")
        continue
    print('MyOdoo Container:' + _mycontainer + '\nDatabase Name:' + _mydb + '\nPort:' + _myport + '\nLongpolling-Port:' + _mypollport)
    print('Path:' + _mypath + '\nImage:' + _myimage + '\n')
    if _myvolumen != "":
        print('Volumen:' + _myvolumen + '\n')
    if _myupdate != "":
        print('Post Update:' + _myupdate)
    if _myvolumen == "":
        os.system('mkdir ' + _mypath + _mydb)
        os.system('docker cp ' + _mycontainer + ':/opt/odoo/data/filestore/' + _mydb + ' ' + _mypath)
        print('Filestore saved...')
    os.chdir(_mypath)
    # Old release manager
    if os.path.isfile(_mypath + 'getMyOdooRelease.sh'):
        print('Get latest release loading...')
        os.system('/bin/bash getMyOdooRelease.sh')
    # release manager
    if os.path.isfile(_mypath + 'check_dockerimage_myodoo.py') and os.path.isfile(_mypath + 'access_myodoo.txt'):
        print('Get latest dockerimages changing...')
        os.system('python check_dockerimage_myodoo.py')
    print(_mycontainer + ' will be stop...')
    os.system('docker stop ' + _mycontainer)
    print(_mycontainer + ' stopped...')
    os.system('docker rm ' + _mycontainer)
    print(_mycontainer + ' removed...')
    os.system('docker rmi ' + _myimage + ':latest')
    print(_myimage + ' removed and  start building..')
    os.system('docker build -t ' + _myimage + ' .')
    if _mytype == "F":
        print(_mycontainer + ' start updating...')
        os.system('docker run -it --rm -p ' + _myport + ':8069 -p ' + _mypollport + ':8072 --name="' + _mycontainer + '" ' + _myvolumen + ' ' + _myimage + ' update --database=' + _mydb + ' --db_user=' + _mydbuser + ' --db_password=' + _mydbpassword + ' --db_host=' + _mydbhost)
    print('docker run -d --restart=always -p ' + _myport + ':8069 -p ' + _mypollport + ':8072 --name="' + _mycontainer + '" ' + _myvolumen + ' ' + _myimage + ' start ')
    os.system('docker run -d --restart=always -p ' + _myport + ':8069 -p ' + _mypollport + ':8072 --name="' + _mycontainer + '" ' + _myvolumen + ' ' + _myimage + ' start')
    if os.path.isfile(_mypath + 'remove_website_menus.py'):
        print('Website menus will remove...')
        time.sleep(_mydelaytime)
        os.system("python " + _mypath + 'remove_website_menus.py')
    if os.path.isfile(_mypath + 'load_translation.py'):
        print('Translation loading...')
        time.sleep(_mydelaytime)
        os.system("python " + _mypath + 'load_translation.py')
        print('Translation loaded...')
    if os.path.isfile(_mypath + 'set_custom_translation.py'):
        print('Translation bugfixes...')
        os.system("python " + _mypath + 'set_custom_translation.py')
        print('Translation bugfixed...')
    print(_mycontainer + ' restarting...')
    if _myupdate != "":
        os.system('docker stop ' + _mycontainer)
        os.system('docker rm ' + _mycontainer)
        print('Post update now')
        print('docker run -d --restart=always -p ' + _myport + ':8069 -p ' + _mypollport + ':8072 --name="' + _mycontainer + '" ' + _myvolumen + ' ' + _myimage + ' start ' + _myupdate)
        os.system('docker run -d --restart=always -p ' + _myupdate + ':8069 -p ' + _myupdate + ':8072 --name="' + _mycontainer + '" ' + _myvolumen + ' ' + _myimage + ' start ' + _myupdate)
        print(_mycontainer + ' restarted...')
    if os.path.exists(_mypath + _mydb + '.bak'):
        os.system('rm -r ' + _mypath + _mydb + '.bak')
    if os.path.exists(_mypath + _mydb):
        os.system('mv ' + _mypath + _mydb + ' ' + _mypath + _mydb + '.bak')
    print('Update is done ' + _mydb)