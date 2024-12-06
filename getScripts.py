#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Dieses Skript hilft beim Organisieren von Docker-Servern
# Version 6.1.1
# Date 06.12.2024
##############################################################################
#
#    Shell Script for devops
#    Copyright © 2014-now Equitania Software GmbH.
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
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import os
import subprocess
import requests
from pathlib import Path
import sys

def is_fastfetch_installed():
    try:
        result = subprocess.run(
            ["fastfetch", "--version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        if result.returncode == 0:
            # Beispielausgabe: "fastfetch 2.31.0 (x86_64)"
            output = result.stdout.strip() or result.stderr.strip()
            parts = output.split()  # ["fastfetch", "2.31.0", "(x86_64)"]
            if len(parts) >= 2:
                version = parts[1]  # "2.31.0"
                return True, version
            else:
                print("Konnte Fastfetch-Version nicht auslesen.")
                return False, None
        else:
            print("Fastfetch Fehler:", result.stderr.strip())
            return False, None
    except FileNotFoundError:
        print("Fastfetch wurde nicht gefunden.")
        return False, None

def is_zoxide_installed():
    try:
        result = subprocess.run(
            ["zoxide", "--version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        if result.returncode == 0:
            # Beispielausgabe: "zoxide 0.9.6"
            output = result.stdout.strip() or result.stderr.strip()
            parts = output.split() # ["zoxide", "0.9.6"]
            if len(parts) >= 2:
                version = parts[1] # "0.9.6"
                return True, version
            else:
                print("Konnte zoxide-Version nicht auslesen.")
                return False, None
        else:
            print("zoxide Fehler:", result.stderr.strip())
            return False, None
    except FileNotFoundError:
        print("zoxide wurde nicht gefunden.")
        return False, None

def download_and_install_deb(url, filename):
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(filename, 'wb') as file:
            file.write(response.content)
        subprocess.run(["sudo", "dpkg", "-i", filename], check=True)
        os.remove(filename)
    except Exception as e:
        print(f"Fehler beim Installieren von {filename}: {e}")
        sys.exit(1)

def install_fastfetch_if_needed():
    DESIRED_VERSION = "2.31.0"
    DEB_URL = f"https://github.com/fastfetch-cli/fastfetch/releases/download/{DESIRED_VERSION}/fastfetch-linux-amd64.deb"
    DEB_FILE = "fastfetch-linux-amd64.deb"

    installed, version = is_fastfetch_installed()
    
    if installed:
        if version == DESIRED_VERSION:
            print(f"Fastfetch Version {DESIRED_VERSION} ist bereits installiert.")
            return
        else:
            print(f"Fastfetch Version {version} ist installiert, aber Version {DESIRED_VERSION} wird benötigt.")
    else:
        print("Fastfetch ist nicht installiert.")
    
    print(f"Lade Fastfetch Version {DESIRED_VERSION} herunter...")
    download_and_install_deb(DEB_URL, DEB_FILE)
    print(f"Fastfetch Version {DESIRED_VERSION} wurde erfolgreich installiert.")

def install_zoxide_if_needed():
    DESIRED_ZOXIDE_VERSION = "0.9.6"
    installed, version = is_zoxide_installed()

    if installed:
        if version == DESIRED_ZOXIDE_VERSION:
            print(f"zoxide Version {DESIRED_ZOXIDE_VERSION} ist bereits installiert.")
            return
        else:
            print(f"zoxide Version {version} ist installiert, aber Version {DESIRED_ZOXIDE_VERSION} wird benötigt.")
    else:
        print("zoxide ist nicht installiert.")

    print(f"Lade zoxide Version {DESIRED_ZOXIDE_VERSION} herunter und installiere...")
    # Installation mittels offiziellem Skript
    run_command("curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash", check=True)
    print(f"zoxide Version {DESIRED_ZOXIDE_VERSION} wurde erfolgreich installiert.")

def ensure_directory_exists(directory):
    os.makedirs(directory, exist_ok=True)
    print(f"Verzeichnis '{directory}' wurde erstellt oder existiert bereits.")

def run_command(command, check=False):
    try:
        subprocess.run(command, shell=True, check=check)
    except subprocess.CalledProcessError as e:
        print(f"Fehler beim Ausführen von '{command}': {e}")
        if check:
            sys.exit(1)

def upgrade_pip_package(package_name):
    run_command(f"pip3 install {package_name} --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")

def main():
    global_server_version = '2024'
    _myhome = os.path.expanduser('~')
    config_directory = os.path.join(_myhome, ".config", "fastfetch")
    ensure_directory_exists(config_directory)

    run_command("sudo timedatectl set-timezone Europe/Berlin", check=True)

    os.chdir(os.path.join(_myhome, "myodoo-docker"))
    run_command(f"git checkout {global_server_version}")
    run_command("git config pull.ff only")
    run_command("git pull")
    run_command("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
    run_command("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
    run_command("cp $HOME/myodoo-docker/scripts/fastfetch/config.jsonc $HOME/.config/fastfetch/")
    
    scripts = [
        "update_docker_myodoo.py",
        "docker-clean-logs.sh",
        "cleanup-weblogs.py",
        "container2backup.py",
        "container2backup_zstd.py",
        "restore-zip.sh",
        "ssl-renew.sh",
        "getScripts.py"
    ]
    
    # Kopieren der Skripte ins Home-Verzeichnis
    for script in scripts:
        run_command(f"cp $HOME/myodoo-docker/{script if script == 'getScripts.py' else f'scripts/{script}'} $HOME")

    os.chdir(_myhome)

    packages = [
        "pip",
        "wheel",
        "setuptools",
        "distro-info",
        "odoorpc-toolbox",
        "nginx-set-conf-equitania",
        "thefuck",
        "odoo-fast-report-mapper-equitania"
    ]

    for package in packages:
        upgrade_pip_package(package)

    # Zoxide Installation nur bei Bedarf
    install_zoxide_if_needed()

    # Überprüfen und Installieren von fastfetch
    install_fastfetch_if_needed()
    
    # .zshrc neu laden
    print("Lade .zshrc neu...")
    run_command("/bin/zsh -c 'source ~/.zshrc'")

if __name__ == "__main__":
    main()