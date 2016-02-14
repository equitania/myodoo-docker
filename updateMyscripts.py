#!/usr/bin/python
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 1.0.0
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

# main
global_server_version = 'master'
os.chdir("/root/myodoo-docker")
os.system("git checkout "+global_server_version)
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp /root/myodoo-docker/bashrc /root/.bashrc")
os.system("cp /root/myodoo-docker/zshrc /root/.zshrc")
os.system("cp /root/myodoo-docker/Scripts/auto_backup_docker.py /root/")
os.system("cp /root/myodoo-docker/Scripts/auto_update_docker_with_same_image.py /root/")
os.system("cp /root/myodoo-docker/Scripts/auto_update_docker.py /root/")
os.system("cp /root/myodoo-docker/Scripts/restore2docker.sh /root/")
os.system("cp -r /root/myodoo-docker/Scripts/nginx-conf /root/")
