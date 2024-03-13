#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 5.4.0
# Date 13.03.2024
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
global_server_version = '2024'
_myhome = os.path.expanduser('~')
_platform = platform.platform()
os.chdir(_myhome + "/" + "myodoo-docker")
os.system("git checkout " + global_server_version)
os.system("git config pull.ff only")
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
os.system("cp $HOME/myodoo-docker/scripts/update_docker_myodoo.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/docker-clean-logs.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/cleanup-weblogs.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/restore-zip.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/ssl-renew.sh $HOME")
os.system("cp $HOME/myodoo-docker/getScripts.py $HOME")
os.chdir(_myhome)

os.system("pip3 install pip --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install wheel --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install setuptools --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install distro-info --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install odoorpc-toolbox --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install nginx-set-conf-equitania --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install thefuck --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("pip3 install odoo-fast-report-mapper-equitania --upgrade --quiet --no-warn-script-location --break-system-packages")
os.system("curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash")
os.system("rm .zcompdump-*")