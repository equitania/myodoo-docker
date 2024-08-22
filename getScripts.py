#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 5.5.3
# Date 22.08.2024
##############################################################################
#
#    Shell Script for devops
#    Copyright © 2014-now Equitania Software GmbH(<http://www.equitania.de>).
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
import subprocess
import requests
from pathlib import Path

# Funktion zur Überprüfung und Installation von fastfetch
def is_fastfetch_installed():
    try:
        result = subprocess.run(["fastfetch", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip().split()[-1]
        else:
            print("Fastfetch repead:", result.stderr)
            return False, None
    except FileNotFoundError:
        print("Fastfetch not found.")
        return False, None

def download_and_install_deb(url, filename):
    response = requests.get(url)
    with open(filename, 'wb') as file:
        file.write(response.content)
    subprocess.run(["sudo", "dpkg", "-i", filename])
    os.remove(filename)

def install_fastfetch_if_needed():
    DESIRED_VERSION = "2.21.3"
    DEB_URL = f"https://github.com/fastfetch-cli/fastfetch/releases/download/{DESIRED_VERSION}/fastfetch-linux-amd64.deb"
    DEB_FILE = "fastfetch-linux-amd64.deb"

    installed, version = is_fastfetch_installed()
    
    if installed:
        if version == DESIRED_VERSION:
            print(f"Fastfetch Version {DESIRED_VERSION} are already installed.")
            return
        else:
            print(f"Fastfetch Version {version} is installed but version {DESIRED_VERSION} is required.")
    else:
        print("Fastfetch is not installed.")
    
    print(f"Loading Fastfetch Version {DESIRED_VERSION} ...")
    download_and_install_deb(DEB_URL, DEB_FILE)
    print(f"Fastfetch Version {DESIRED_VERSION} was successfully installed.")

def ensure_directory_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"Directory '{directory}' was created.")
    else:
        print(f"Directory '{directory}' already exists.")

# main
global_server_version = '2024'
_myhome = os.path.expanduser('~')
config_directory = os.path.join(_myhome, ".config", "fastfetch")
ensure_directory_exists(config_directory)
os.system("sudo timedatectl set-timezone Europe/Berlin")
os.chdir(_myhome + "/" + "myodoo-docker")
os.system("git checkout " + global_server_version)
os.system("git config pull.ff only")
os.system("git pull")
os.system("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
os.system("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
os.system("cp $HOME/myodoo-docker/scripts/fastfetch/config.jsonc $HOME/.config/fastfetch/")
os.system("cp $HOME/myodoo-docker/scripts/update_docker_myodoo.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/docker-clean-logs.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/cleanup-weblogs.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/container2backup_zstd.py $HOME")
os.system("cp $HOME/myodoo-docker/scripts/restore-zip.sh $HOME")
os.system("cp $HOME/myodoo-docker/scripts/ssl-renew.sh $HOME")
os.system("cp $HOME/myodoo-docker/getScripts.py $HOME")
os.chdir(_myhome)

os.system("pip3 install pip --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install wheel --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install setuptools --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install distro-info --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install odoorpc-toolbox --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install nginx-set-conf-equitania --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install thefuck --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install odoo-fast-report-mapper-equitania --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install nginx-set-conf-equitania --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install thefuck --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("pip3 install odoo-fast-report-mapper-equitania --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")
os.system("curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash")
os.system("rm .zcompdump-*")

# Überprüfen und Installieren von fastfetch
install_fastfetch_if_needed()

# .zshrc neu laden
print("Reloading .zshrc...")
os.system("/bin/zsh -c 'source ~/.zshrc'")