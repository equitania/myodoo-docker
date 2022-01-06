#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 4.0.0
# Date 06.01.2022
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
from pathlib import Path

# main
global_server_version = '2022'
_myhome = os.path.expanduser('~')
os.chdir(_myhome + "/" + "myodoo-docker")
os.system("git checkout " + global_server_version)
os.system("git config pull.ff only")
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
os.system("cp $HOME/myodoo-docker/scripts/update_docker_myodoo.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/cleanup-weblogs.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/ssl-renew.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/restore-zip.sh $HOME")
os.system("cp $HOME/myodoo-docker/getScripts.py $HOME")
os.chdir(_myhome)
os.system("python3 -m pip install --user pip --user --upgrade --no-warn-script-location")
os.system("python3 -m pip install --user wheel --upgrade --no-warn-script-location")
os.system("python3 -m pip install --user setuptools --upgrade --no-warn-script-location")
# https://pypi.org/project/OdooRPC/
os.system("python3 -m pip install --user odoorpc --upgrade --no-warn-script-location")
# https://pypi.org/project/click/
os.system("python3 -m pip install --user click --upgrade --no-warn-script-location")
# https://pypi.org/project/bpytop/
os.system("python3 -m pip install --user bpytop --upgrade --no-warn-script-location")
#https://pypi.org/project/odoo-fast-report-mapper-equitania/
os.system("python3 -m pip install --user odoo-fast-report-mapper-equitania --upgrade --no-warn-script-location")
# https://pypi.org/project/nginx-set-conf-equitania/
os.system("python3 -m pip install --user nginx-set-conf-equitania --upgrade --no-warn-script-location")
os.system("wget https://rm.myodoo.net/staff/neofetch/config.conf -O $HOME/.config/neofetch/config.conf")
# https://github.com/jesseduffield/lazydocker
os.system("curl https://raw.githubusercontent.com/jesseduffield/lazydocker/master/scripts/install_update_linux.sh | bash")
_nano_path = _myhome + "/.nano/backups/"
_nano_path_check = Path(_nano_path)
if _nano_path_check.exists():
    os.system("rm $HOME/.nanorc && cd $HOME && wget https://rm.myodoo.net/staff/.nanorc")
else:
    os.system("mkdir -p $HOME/.nano/backups/ && wget https://raw.githubusercontent.com/scopatz/nanorc/master/install.sh -O- | sh && rm $HOME/.nanorc && cd $HOME && wget https://rm.myodoo.net/staff/.nanorc")
# https://github.com/FrederikRogalski/compose-update
_cu_path = _myhome + "/compose-update"
_cu_path_check = Path(_cu_path)
if _cu_path_check.exists():
    os.chdir(_cu_path)
    os.system("git config pull.ff only")
    os.system("git pull")
    os.system("chmod +x compose-update")
else:
    os.system("git clone https://github.com/FrederikRogalski/compose-update.git")
    os.chdir(_cu_path)
    os.system("pip3 install -r requirements.txt")
    os.system("chmod +x compose-update")
os.chdir(_myhome)
