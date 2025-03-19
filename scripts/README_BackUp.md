# Odoo Docker Backup-System

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

## Übersicht

Dieses Backup-System sichert Odoo-Datenbanken, Docker-Container und zusätzliche Dienste in 7-Zip-Archive. Es wurde entwickelt, um komplette Backups von Odoo-Installationen zu erstellen, die in Docker-Containern laufen.

### Hauptfunktionen

- Backup von mehreren Odoo-Datenbanken (SQL-Dump + Filestore)
- Backup von FastReport-Dateien pro Datenbank
- Backup zusätzlicher Dienste (Nginx, Let's Encrypt, Docker-Builds)
- Komprimierung mit 7-Zip mit einstellbarem Kompressionsgrad
- Optionale AES-256 Verschlüsselung
- Automatische Verwaltung von alten Backups
- Konfiguration über YAML-Datei

## Installation

1. Installieren Sie die benötigten Pakete:
   ```bash
   sudo apt-get install p7zip-full
   pip3 install python-dotenv pyyaml
   ```

2. Kopieren Sie das Skript in ein Verzeichnis Ihrer Wahl.

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
    backup_path: letsencrypt
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

### Kompressionskonfiguration

Der 7-Zip Kompressionsgrad kann im `defaults`-Bereich konfiguriert werden:
- Wertebereich: 0-9
  - 0: Keine Kompression (nur Archivierung)
  - 1-2: Schnelle Kompression
  - 3-6: Ausgewogene Kompression
  - 5: Standard
  - 7-9: Beste Kompression (langsamer)

## Dateistruktur und Speicherorte

### 1. Hauptbackup-Verzeichnis

Standardmäßig werden alle Backups im Verzeichnis `/opt/backups` gespeichert, sofern nicht anders konfiguriert:

## Aufräumen alter Backups

- Jeder Backup-Typ kann eine eigene Aufbewahrungsfrist haben (in Tagen)
- Nach Ablauf dieser Frist werden **alle Dateien** im entsprechenden Backup-Verzeichnis gelöscht, unabhängig von der Dateiendung
- Die Aufbewahrungsfrist wird für jeden Service und jede Datenbank separat eingestellt
- Achten Sie darauf, keine anderen wichtigen Dateien in den Backup-Verzeichnissen zu speichern, da diese ebenfalls gelöscht werden könnten

## Cleaning up Old Backups

- Each backup type can have its own retention period (in days)
- After this period, **all files** in the respective backup directory will be deleted, regardless of file extension
- The retention period is set separately for each service and database
- Be careful not to store other important files in the backup directories, as they could also be deleted

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