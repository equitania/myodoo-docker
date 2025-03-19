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

2. Kopieren Sie das Skript in ein Verzeichnis Ihrer Wahl (z.B. `/opt/scripts/`).

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

```
/opt/backups/
├── docker/         # Odoo-Datenbank-Backups
├── nginx/          # Nginx-Konfigurationen
├── letsencrypt/    # Let's Encrypt-Zertifikate
└── docker-builds/  # Docker Build Konfigurationen
```

### 2. Datenbankbackups

Datenbankbackups befinden sich im Unterverzeichnis `docker` und enthalten die folgenden Elemente:

**Dateinamensformat:** `{db_name}_{container}_dockerbackup_{timestamp}.7z`

**Interne Struktur des 7z-Archivs:**
```
/
├── dump.sql       # SQL-Dump der Datenbank
└── {db_name}/     # Filestore-Dateien, direkt mit Datenbanknamen beginnend
    ├── file1
    ├── file2
    └── ...
```

### 3. FastReport-Backups

FastReport-Backups werden separat erstellt und im gleichen `docker`-Verzeichnis wie die Datenbankbackups gespeichert:

**Dateinamensformat:** `{db_name}_FastReport_{timestamp}.7z`

**Interne Struktur des 7z-Archivs:**
```
/
└── {Original FastReport Verzeichnisstruktur}
```

### 4. Service-Backups

Service-Backups werden in ihren eigenen Unterverzeichnissen gespeichert:

**Nginx:**
- Dateipfad: `/opt/backups/nginx/nginx_{timestamp}.7z`
- Enthält: Komplette Nginx-Konfiguration

**Let's Encrypt:**
- Dateipfad: `/opt/backups/letsencrypt/letsencrypt_{timestamp}.7z`
- Enthält: Let's Encrypt-Zertifikate und -Konfiguration

**Docker-Builds:**
- Dateipfad: `/opt/backups/docker-builds/docker-builds_{timestamp}.7z`
- Enthält: Docker-Build-Konfigurationen und Dockerfiles

## Verschlüsselung

Die Verschlüsselung ist optional und kann über eine `.env`-Datei aktiviert werden:

1. Erstellen Sie eine `.env`-Datei im selben Verzeichnis wie das Skript:
   ```
   BACKUP_ENCRYPTION_ENABLED=true
   BACKUP_PASSWORD=IhrSicheresPasswort
   ```

2. Mit dieser Konfiguration werden alle Backups mit AES-256 verschlüsselt und die Header-Verschlüsselung aktiviert.

## Backup-Prozess

1. Datenbankbackup:
   - SQL-Dump wird aus dem SQL-Container extrahiert
   - Filestore wird aus dem Odoo-Container extrahiert
   - Beide werden in ein 7z-Archiv komprimiert

2. FastReport-Backup:
   - Separat vom Datenbankbackup erstellt
   - Direkt vom Host-Dateisystem komprimiert

3. Service-Backups:
   - Nginx, Let's Encrypt, Docker-Builds werden separat gesichert
   - Direkt vom Host-Dateisystem komprimiert

4. Remote-Synchronisation:
   - Optional über rsync-Kommandos konfigurierbar
   - Nach Abschluss aller Backups ausgeführt

## Aufräumen alter Backups

- Jeder Backup-Typ kann eine eigene Aufbewahrungsfrist haben (in Tagen)
- Nach Ablauf dieser Frist werden Dateien im entsprechenden Backup-Verzeichnis nach dem jeweiligen Präfix (Datenbankname oder Service-Name) gelöscht
- Die Aufbewahrungsfrist wird für jeden Service und jede Datenbank separat eingestellt
- Achten Sie darauf, keine anderen wichtigen Dateien in den Backup-Verzeichnissen zu speichern, die den gleichen Präfix haben

## Automatisierung mit Cron

Sie können das Backup-Skript über einen Cron-Job automatisieren:

1. Öffnen Sie die Crontab-Datei:
   ```bash
   crontab -e
   ```

2. Fügen Sie eine Zeile hinzu, um das Backup täglich um 2 Uhr morgens auszuführen:
   ```bash
   0 2 * * * python3 /pfad/zu/container2backup.py
   ```

---

<a id="english-version"></a>
# English Version

## Overview

This backup system secures Odoo databases, Docker containers, and additional services in 7-Zip archives. It was designed to create complete backups of Odoo installations running in Docker containers.

### Main Features

- Backup of multiple Odoo databases (SQL dump + filestore)
- Backup of FastReport files per database
- Backup of additional services (Nginx, Let's Encrypt, Docker builds)
- Compression with 7-Zip with adjustable compression level
- Optional AES-256 encryption
- Automatic management of old backups
- Configuration via YAML file

## Installation

1. Install the required packages:
   ```bash
   sudo apt-get install p7zip-full
   pip3 install python-dotenv pyyaml
   ```

2. Copy the script to a directory of your choice (e.g., `/opt/scripts/`).

## Configuration

Configuration is done via the YAML file `container2backup.yaml` in the user's home directory.

### Example Configuration:

```yaml
# Backup configuration for Odoo databases
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression:
    level: 5  # 7-Zip compression level (0-9)

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

### Compression Configuration

The 7-Zip compression level can be configured in the `defaults` section:
- Range: 0-9
  - 0: No compression (archiving only)
  - 1-2: Fast compression
  - 3-6: Balanced compression
  - 5: Default
  - 7-9: Best compression (slower)

## File Structure and Storage Locations

### 1. Main Backup Directory

By default, all backups are stored in the `/opt/backups` directory, unless configured otherwise:

```
/opt/backups/
├── docker/         # Odoo database backups
├── nginx/          # Nginx configurations
├── letsencrypt/    # Let's Encrypt certificates
└── docker-builds/  # Docker build configurations
```

### 2. Database Backups

Database backups are located in the `docker` subdirectory and contain the following elements:

**Filename format:** `{db_name}_{container}_dockerbackup_{timestamp}.7z`

**Internal structure of the 7z archive:**
```
/
├── dump.sql       # SQL dump of the database
└── {db_name}/     # Filestore files, starting directly with the database name
    ├── file1
    ├── file2
    └── ...
```

### 3. FastReport Backups

FastReport backups are created separately and stored in the same `docker` directory as the database backups:

**Filename format:** `{db_name}_FastReport_{timestamp}.7z`

**Internal structure of the 7z archive:**
```
/
└── {Original FastReport directory structure}
```

### 4. Service Backups

Service backups are stored in their own subdirectories:

**Nginx:**
- File path: `/opt/backups/nginx/nginx_{timestamp}.7z`
- Contains: Complete Nginx configuration

**Let's Encrypt:**
- File path: `/opt/backups/letsencrypt/letsencrypt_{timestamp}.7z`
- Contains: Let's Encrypt certificates and configuration

**Docker Builds:**
- File path: `/opt/backups/docker-builds/docker-builds_{timestamp}.7z`
- Contains: Docker build configurations and Dockerfiles

## Encryption

Encryption is optional and can be activated via a `.env` file:

1. Create a `.env` file in the same directory as the script:
   ```
   BACKUP_ENCRYPTION_ENABLED=true
   BACKUP_PASSWORD=YourSecurePassword
   ```

2. With this configuration, all backups will be encrypted with AES-256 and header encryption will be enabled.

## Backup Process

1. Database backup:
   - SQL dump is extracted from the SQL container
   - Filestore is extracted from the Odoo container
   - Both are compressed into a 7z archive

2. FastReport backup:
   - Created separately from the database backup
   - Compressed directly from the host file system

3. Service backups:
   - Nginx, Let's Encrypt, Docker builds are backed up separately
   - Compressed directly from the host file system

4. Remote synchronization:
   - Optionally configurable via rsync commands
   - Executed after completion of all backups

## Cleaning up Old Backups

- Each backup type can have its own retention period (in days)
- After this period, files in the corresponding backup directory are deleted according to their prefix (database name or service name)
- The retention period is set separately for each service and database
- Be careful not to store other important files in the backup directories that have the same prefix

## Automation with Cron

You can automate the backup script via a cron job:

1. Open the crontab file:
   ```bash
   crontab -e
   ```

2. Add a line to run the backup daily at 2 AM:
   ```bash
   0 2 * * * python3 /path/to/container2backup.py
   ```


