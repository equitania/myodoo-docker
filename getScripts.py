#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 5.0.0
# Date 07.12.2022
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
import platform
from pathlib import Path

# main
global_server_version = '2023'
_myhome = os.path.expanduser('~')
_platform = platform.platform()
os.chdir(_myhome + "/" + "myodoo-docker")
os.system("git checkout " + global_server_version)
os.system("git config pull.ff only")
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
os.system("cp $HOME/myodoo-docker/scripts/update_docker_myodoo.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/restore-zip.sh $HOME")
os.system("cp $HOME/myodoo-docker/getScripts.py $HOME")
os.chdir(_myhome)
os.system("python3 -m pip install --user pip --user --upgrade --no-warn-script-location")
os.system("python3 -m pip install --user wheel --upgrade --no-warn-script-location")
os.system("python3 -m pip install --user setuptools --upgrade --no-warn-script-location")
# https://pypi.org/project/OdooRPC/
os.system("python3 -m pip install --user odoorpc-toolbox --upgrade --no-warn-script-location")
_nano_path = _myhome + "/.nano/backups/"
_nano_path_check = Path(_nano_path)
if not _nano_path_check.exists():
    os.system("mkdir -p $HOME/.nano/backups/ && wget https://raw.githubusercontent.com/scopatz/nanorc/master/install.sh -O- | sh")
if 'alma' in _platform:
    os.system("rm $HOME/.nanorc && cd $HOME && curl -k -o .nanorc -SL https://rm.myodoo.net/staff/.nanorc.alma")
else:    
    os.system("rm $HOME/.nanorc && cd $HOME && wget https://rm.myodoo.net/staff/.nanorc")
