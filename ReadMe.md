# Myodoo-Docker

(c) 2016 till now by Equitania Software GmbH

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

<a name="deutsch"></a>
## Deutsch

### Über dieses Repository

Dieses Repository enthält eine Sammlung von Docker-Konfigurationen und Verwaltungsskripten für Odoo-Installationen. Es wird täglich in der professionellen Administration von Kundensystemen eingesetzt.

### Schnellstart

```bash
# Erstmalige Installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py
```

### Hauptkomponenten

#### 1. Verwaltungsskripte

- **getScripts.py**
  - Hauptinstallationsskript
  - Installiert alle benötigten Werkzeuge und Abhängigkeiten
  - Aktualisiert bestehende Installationen

- **container2backup.py**
  - Automatisches Backup-System für Odoo-Datenbanken
  - Sichert Datenbank, Filestore und zusätzliche Pfade
  - Konfiguration über YAML-Datei
  - Optionale AES-256 Verschlüsselung
  - Automatische Bereinigung alter Backups
  ```yaml
  # Beispiel container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      level: 5  # 7-Zip Kompressionsgrad (0-9)
  ```

- **update_docker_odoo.py**
  - Automatisierte Aktualisierung von Docker-Containern
  - Sicherheitsrelevante Updates
  - Neustart von Diensten

#### 2. Systemkonfigurationen

- Nginx-Konfigurationen für Reverse Proxy
- Let's Encrypt SSL-Integration
- Docker-Build-Konfigurationen

#### 3. Sicherheitsfeatures

- Verschlüsselte Backups (AES-256)
- Automatische SSL-Zertifikatserneuerung
- Sichere Standardkonfigurationen

#### 4. Shell-Aliasse

Die ZSH-Konfiguration enthält nützliche Aliasse für die tägliche Arbeit:

##### Grundlegende Aliasse
- `ls` - verbesserte Verzeichnisanzeige
- `ll` - ausführliche Verzeichnisanzeige
- `lg` - Lazygit-Shortcut 
- `grep` - Ausgabe mit Farbhervorhebung
- `nano` - Nano mit besseren Standardoptionen
- `hg` - History-Suche
- `nf` - Neofetch ausführen
- `ff` - Fastfetch ausführen
- `mce` - Shortcut für mcedit
- `rm` - sichereres Löschen mit Bestätigung
- `chmod` - mit Änderungsanzeige
- `chown` - mit Änderungsanzeige
- `shred` - sicheres Löschen von Dateien
- `bat` - Alias für batcat

##### Nginx-Aliasse
- `cdngx` - Wechsel ins Nginx-Konfigurationsverzeichnis
- `ngx+` - Nginx starten
- `ngx-` - Nginx stoppen
- `ngx#` - Nginx neu starten
- `ngxr` - Nginx-Konfiguration neu laden
- `ngxs` - Nginx-Status anzeigen
- `ngx!` - Nginx-Konfigurationstest
- `ngxl` - Nginx-Test mit spezifischer Konfigurationsdatei
- `ngxset` - Nginx-Konfiguration setzen
- `showcerts` - Zertifikate anzeigen

##### System-Aliasse
- `prepatch` - Systemupdate in einer Screen-Session vorbereiten
- `cleandlog` - Docker-Logs bereinigen
- `syspatch` - Umfassende Systemaktualisierung und Bereinigung (apt-basiert)
- `syspatcha` - Alternative Systemaktualisierung (dnf-basiert)
- `dusort` - Verzeichnisgrößen sortiert anzeigen
- `f2b` - Fail2ban-Client-Status anzeigen
- `ups` - Update der ownERP-Skripte

##### ownERP-Aliasse
- `dobk` - Ausführen des Backup-Skripts
- `doup` - Aktualisieren der Docker-Container
- `doup2` - Alternative Docker-Container-Aktualisierung
- `edbk` - Backup-Konfiguration bearbeiten (YAML)
- `edbk2` - Alternative Backup-Konfiguration bearbeiten (CSV)
- `edup` - Update-Konfiguration bearbeiten (YAML)
- `edup2` - Alternative Update-Konfiguration bearbeiten (CSV)
- `llbk` - Backup-Verzeichnis auflisten
- `cpbk` - Kopieren aus dem Backup-Verzeichnis

##### Docker-Aliasse
- `dk` - Shortcut für docker
- `dps` - Docker-Container übersichtlich auflisten
- `dpsall` - Erweiterte Docker-Container-Auflistung
- `dpi` - Docker-Images anzeigen
- `dkpsf` - Docker-Containerkommandos anzeigen
- `dkvol` - Docker-Volumes überprüfen
- `dkstop` - Alle Container stoppen
- `dkrm` - Alle Container entfernen
- `dkrmi` - Alle Images entfernen
- `dkrmv` - Alle Docker-Volumes entfernen
- `dkprs` - Docker-System bereinigen
- `dkprv` - Docker-Volumes bereinigen
- `dkprf` - Komplette Docker-Systembereinigung
- `dkprfa` - Komplette Docker-Systembereinigung inkl. Volumes
- `ox` - Shortcut für oxker
- `dkprfs` - docker system cleanup with force option

### Branch-Verwaltung

```bash
# Wechsel zu einer spezifischen Version (z.B. 2025)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2025 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```

---

<a name="english"></a>
## English

### About this Repository

This repository contains a collection of Docker configurations and management scripts for Odoo installations. It is used daily in professional customer system administration.

### Quick Start

```bash
# Initial Installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py
```

### Main Components

#### 1. Management Scripts

- **getScripts.py**
  - Main installation script
  - Installs all required tools and dependencies
  - Updates existing installations

- **container2backup.py**
  - Automatic backup system for Odoo databases
  - Backs up database, filestore, and additional paths
  - Configuration via YAML file
  - Optional AES-256 encryption
  - Automatic cleanup of old backups
  ```yaml
  # Example container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      level: 5  # 7-Zip compression level (0-9)
  ```

- **update_docker_odoo.py**
  - Automated Docker container updates
  - Security-relevant updates
  - Service restart management

#### 2. System Configurations

- Nginx configurations for reverse proxy
- Let's Encrypt SSL integration
- Docker build configurations

#### 3. Security Features

- Encrypted backups (AES-256)
- Automatic SSL certificate renewal
- Secure default configurations

#### 4. Shell Aliases

The ZSH configuration includes useful aliases for daily work:

##### Basic Aliases
- `ls` - enhanced directory listing
- `ll` - detailed directory listing
- `lg` - lazygit shortcut
- `grep` - output with color highlighting
- `nano` - nano with better default options
- `hg` - history search
- `nf` - run neofetch
- `ff` - run fastfetch
- `mce` - shortcut for mcedit
- `rm` - safer removal with confirmation
- `chmod` - with change display
- `chown` - with change display
- `shred` - secure file deletion
- `bat` - alias for batcat

##### Nginx Aliases
- `cdngx` - change to nginx configuration directory
- `ngx+` - start nginx
- `ngx-` - stop nginx
- `ngx#` - restart nginx
- `ngxr` - reload nginx configuration
- `ngxs` - show nginx status
- `ngx!` - test nginx configuration
- `ngxl` - test nginx with specific config file
- `ngxset` - set nginx configuration
- `showcerts` - show certificates

##### System Aliases
- `prepatch` - prepare system update in a screen session
- `cleandlog` - clean docker logs
- `syspatch` - comprehensive system update and cleanup (apt-based)
- `syspatcha` - alternative system update (dnf-based)
- `dusort` - show directory sizes sorted
- `f2b` - show fail2ban client status
- `ups` - update ownERP scripts

##### ownERP Aliases
- `dobk` - run backup script
- `doup` - update docker containers
- `doup2` - alternative docker container update
- `edbk` - edit backup configuration (YAML)
- `edbk2` - edit alternative backup configuration (CSV)
- `edup` - edit update configuration (YAML)
- `edup2` - edit alternative update configuration (CSV)
- `llbk` - list backup directory
- `cpbk` - copy from backup directory

##### Docker Aliases
- `dk` - shortcut for docker
- `dps` - list docker containers in a clear format
- `dpsall` - extended docker container listing
- `dpi` - show docker images
- `dkpsf` - show docker container commands
- `dkvol` - check docker volumes
- `dkstop` - stop all containers
- `dkrm` - remove all containers
- `dkrmi` - remove all images
- `dkrmv` - remove all docker volumes
- `dkprs` - clean docker system
- `dkprv` - clean docker volumes
- `dkprf` - complete docker system cleanup
- `dkprfa` - complete docker system cleanup incl. volumes
- `ox` - shortcut for oxker
- `dkprfs` - docker system cleanup with force option

### Branch Management

```bash
# Switch to a specific version (e.g., 2024)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2025 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```

---

For more information:
- [ownERP.com](https://www.ownerp.com)

