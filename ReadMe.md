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

### Branch-Verwaltung

```bash
# Wechsel zu einer spezifischen Version (z.B. 2024)
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

