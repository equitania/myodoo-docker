# Backup-System für Odoo, Docker und weitere Dienste

Dieses Backup-System sichert Odoo-Datenbanken, Docker-Container und zusätzliche Dienste in 7-Zip-Archive.

## Übersicht

Das System unterstützt folgende Backup-Typen:
- Odoo-Datenbanken (SQL-Dump + Filestore)
- FastReport-Dateien pro Datenbank 
- Zusätzliche Dienste (Nginx, Let's Encrypt, Docker-Builds)
- Benutzerdefinierte Dateiverzeichnisse

## Konfiguration

Die Konfiguration erfolgt über die YAML-Datei `container2backup.yaml` im Home-Verzeichnis des Benutzers.

### Beispielkonfiguration:

```yaml
# Backup-Konfiguration für Odoo-Datenbanken
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression:
    level: 5  # 7-Zip Kompressionsgrad (0-9)

services:
  nginx:
    enabled: true
    source_path: /etc/nginx
    backup_path: nginx
    retention_days: 14

  letsencrypt:
    enabled: true
    source_path: /etc/letsencrypt
    backup_path: nginx
    retention_days: 14

  docker_builds:
    enabled: true
    source_path: $HOME/docker-builds
    backup_path: docker-builds
    retention_days: 14

databases:
  - name: live_db
    sql_container: live-db
    data_container: live-odoo
    retention_days: 5
    fast_report:
      enabled: true
      path: /opt/fast-report/live

  - name: test_db
    sql_container: test-db
    data_container: test-odoo
    retention_days: 5

rsync:
  enabled: true
  commands:
    - "rsync -avz /opt/backups/docker/ user@remote-server:/backup/docker/"
```

## Dateistruktur und Speicherorte

### 1. Hauptbackup-Verzeichnis

Standardmäßig werden alle Backups im Verzeichnis `/opt/backups` gespeichert, sofern nicht anders konfiguriert:

# Odoo Docker Backup Script

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

## Deutsche Version

## Über dieses Skript

Dieses Skript erstellt automatisierte Backups von Odoo-Datenbanken, die in Docker-Containern laufen. Es sichert sowohl die PostgreSQL-Datenbank als auch den FileStore, zusätzliche Systempfade und unterstützt mehrere Odoo-Instanzen.

### Hauptfunktionen

- Backup von mehreren Odoo-Datenbanken
- Komprimierung mit 7-Zip
- Optionale AES-256 Verschlüsselung
- Automatische Verwaltung von alten Backups
- Backup zusätzlicher Pfade (Nginx, Let's Encrypt, Fast-Report, usw.)

### Voraussetzungen

1. Python 3.6 oder höher
2. Docker
3. 7-Zip (`p7zip-full` Paket)
4. python-dotenv (für Verschlüsselung)

### Installation

1. Installieren Sie die benötigten Pakete:
   ```bash
   sudo apt-get install p7zip-full
   pip3 install python-dotenv pyyaml
   ```

2. Kopieren Sie das Skript in ein Verzeichnis Ihrer Wahl (z.B. `/opt/scripts/`).

### Konfiguration

Das Skript verwendet eine YAML-Konfigurationsdatei:

```yaml
# Default settings
defaults:
  retention_days: 14  # Aufbewahrungsfrist in Tagen
  db_user: ownerp
  backup_path: /opt/backups
  compression:
    level: 5  # 7-Zip Kompressionsgrad (0-9)

# System-wide service backups
services:
  nginx:
    enabled: true
    source_path: /etc/nginx
    backup_path: nginx
    retention_days: 14

  letsencrypt:
    enabled: true
    source_path: /etc/letsencrypt/live
    backup_path: nginx
    retention_days: 14

  docker_builds:
    enabled: true
    source_path: /root/docker-builds
    backup_path: docker-builds
    retention_days: 14

# Database specific configurations
databases:
  - name: live_db
    sql_container: live-db
    data_container: live-myodoo
    retention_days: 5
    fast_report:  # Optional fast-report configuration
      enabled: true
      path: /opt/fast-report/live

  - name: test_db
    sql_container: test-db
    data_container: test-myodoo
    retention_days: 5
    fast_report:
      enabled: true
      path: /opt/fast-report/test
```

#### Kompressionskonfiguration

Der 7-Zip Kompressionsgrad kann im `defaults`-Bereich konfiguriert werden:
- Wertebereich: 0-9
  - 0: Keine Kompression (nur Archivierung)
  - 1: Schnellste Kompression
  - 5: Standard-Kompression (gute Balance)
  - 9: Beste Kompression (langsamer)

### Verwendung

#### Grundlegende Verwendung:

```bash
python3 container2backup_enhanced.py
```

#### Mit einer bestimmten Konfigurationsdatei:

```bash
python3 container2backup_enhanced.py --config /pfad/zur/backup_config.yaml
```

#### Weitere Optionen:

```bash
python3 container2backup_enhanced.py --help
```

### Automatisierung mit Cron

Sie können das Backup-Skript über einen Cron-Job automatisieren:

1. Öffnen Sie die Crontab-Datei:
   ```bash
   crontab -e
   ```

2. Fügen Sie eine Zeile für die tägliche Ausführung hinzu:
   ```
   0 2 * * * python3 /pfad/zu/container2backup_enhanced.py
   ```
   (Führt das Skript täglich um 2 Uhr morgens aus)

### Automatisierung mit systemd

Alternativ können Sie einen systemd-Service einrichten:

```bash
python3 container2backup_enhanced.py --create-service
```

Folgen Sie dann den angezeigten Anweisungen.

### Fehlerbehebung

- **Das Backup schlägt fehl**: Überprüfen Sie die Logdatei unter `[backup_root]/logs/backup.log`
- **Nicht genügend Speicherplatz**: Erhöhen Sie den verfügbaren Speicherplatz oder verringern Sie `min_disk_space_gb` in der Konfiguration
- **Container nicht erreichbar**: Stellen Sie sicher, dass die Container-Namen in der Konfiguration korrekt sind und die Container laufen
- **Kompressionsbefehl fehlt**: Installieren Sie die benötigten Pakete für Ihr gewähltes Kompressionsformat

---

## English Version

## About this Script

This script creates automated backups of Odoo databases running in Docker containers. It backs up both the PostgreSQL database and the FileStore, additional system paths, and supports multiple Odoo instances.

### Key Features

- Backup of multiple Odoo databases
- Compression using 7-Zip
- Optional AES-256 encryption
- Automatic management of old backups
- Backup of additional paths (Nginx, Let's Encrypt, Fast-Report, etc.)

### Requirements

1. Python 3.6 or higher
2. Docker
3. 7-Zip (`p7zip-full` package)
4. python-dotenv (for encryption)

### Installation

1. Install required packages:
   ```bash
   sudo apt-get install p7zip-full
   pip3 install python-dotenv pyyaml
   ```

2. Copy the script to a directory of your choice (e.g., `/opt/scripts/`).

### Configuration

The script uses a YAML configuration file:

```yaml
# Default settings
defaults:
  retention_days: 14  # Retention period in days
  db_user: ownerp
  backup_path: /opt/backups
  compression:
    level: 5  # 7-Zip compression level (0-9)

# System-wide service backups
services:
  nginx:
    enabled: true
    source_path: /etc/nginx
    backup_path: nginx
    retention_days: 14

  letsencrypt:
    enabled: true
    source_path: /etc/letsencrypt/live
    backup_path: nginx
    retention_days: 14

  docker_builds:
    enabled: true
    source_path: /root/docker-builds
    backup_path: docker-builds
    retention_days: 14

# Database specific configurations
databases:
  - name: live_db
    sql_container: live-db
    data_container: live-myodoo
    retention_days: 5
    fast_report:  # Optional fast-report configuration
      enabled: true
      path: /opt/fast-report/live

  - name: test_db
    sql_container: test-db
    data_container: test-myodoo
    retention_days: 5
    fast_report:
      enabled: true
      path: /opt/fast-report/test
```

#### Compression Configuration

The 7-Zip compression level can be configured in the `defaults` section:
- Value range: 0-9
  - 0: No compression (store only)
  - 1: Fastest compression
  - 5: Default compression (good balance)
  - 9: Best compression (slower)

### Usage

#### Basic Usage:

```bash
python3 container2backup_enhanced.py
```

#### With a specific configuration file:

```bash
python3 container2backup_enhanced.py --config /path/to/backup_config.yaml
```

#### More Options:

```bash
python3 container2backup_enhanced.py --help
```

### Automation with Cron

You can automate the backup script using a cron job:

1. Open the crontab file:
   ```bash
   crontab -e
   ```

2. Add a line for daily execution:
   ```
   0 2 * * * python3 /path/to/container2backup_enhanced.py
   ```
   (Runs the script daily at 2 AM)

### Automation with systemd

Alternatively, you can set up a systemd service:

```bash
python3 container2backup_enhanced.py --create-service
```

Then follow the displayed instructions.

### Troubleshooting

- **Backup fails**: Check the log file at `[backup_root]/logs/backup.log`
- **Not enough disk space**: Increase available disk space or decrease `min_disk_space_gb` in the configuration
- **Container not accessible**: Make sure the container names in the configuration are correct and the containers are running
- **Compression command missing**: Install the required packages for your chosen compression format 