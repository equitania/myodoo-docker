#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 3.1.7
# Date 25.04.2021
##############################################################################
#
#    Shell Script for devops
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

# main
global_server_version = '2020'
myhome = os.path.expanduser('~')
os.chdir(myhome + "/" + "myodoo-docker")
os.system("git checkout "+global_server_version)
os.system("git config pull.ff only")
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp $HOME/myodoo-docker/.bashrc $HOME/.bashrc")
os.system("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
os.system("rm -rf $HOME/nginx-conf")
os.system("cp -r $HOME/myodoo-docker/nginx-conf $HOME")
os.system("cp $HOME/myodoo-docker/scripts/update_docker_myodoo.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/cleanup-weblogs.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/ssl-renew.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/restore-zip.sh $HOME")
os.system("cp $HOME/myodoo-docker/getScripts.py $HOME")
os.system("python3 -m pip install pip --upgrade --user")
os.system("python3 -m pip install wheel --upgrade --user")
os.system("python3 -m pip install odoorpc --upgrade --user")
os.system("python3 -m pip install click --upgrade --user")
os.system("python3 -m pip install bpytop --upgrade --user")
os.system("wget https://rm.myodoo.net/staff/neofetch/config.conf -O $HOME/.config/neofetch/config.conf")