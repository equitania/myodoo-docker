# Odoo Docker Backup-System

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

## Übersicht

Dieses Backup-System sichert Odoo-Datenbanken, Docker-Container und zusätzliche Dienste in komprimierte Archive. Es wurde entwickelt, um komplette Backups von Odoo-Installationen zu erstellen, die in Docker-Containern laufen.

### Hauptfunktionen

- Backup von mehreren Odoo-Datenbanken (SQL-Dump + Filestore)
- Backup von FastReport-Dateien pro Datenbank
- Backup zusätzlicher Dienste (Nginx, Let's Encrypt, Docker-Builds)
- Verschiedene Kompressionsformate mit einstellbarem Kompressionsgrad
- Optionale AES-256 Verschlüsselung (nur mit 7z-Format)
- Automatische Verwaltung von alten Backups
- Konfiguration über YAML-Datei

## Installation

1. Installieren Sie die benötigten Pakete:
   ```bash
   sudo apt-get install 7zip zstd
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
    format: "7z"     # Kompressionsformat: 7z, zip, gzip, zstd
    level: 5         # Kompressionsgrad (0-9, Standard: 5)

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
    only_sql_dump: false  # Optional: SQL-Dump und Filestore sichern (Standardverhalten)
    fast_report:
      enabled: true
      path: /opt/fast-report/live

  - name: test_db
    sql_container: test-db
    data_container: test-odoo
    retention_days: 5
    only_sql_dump: true   # Nur SQL-Dump sichern, Filestore überspringen
    fast_report:
      enabled: true
      path: /opt/fast-report/test

rsync:
  enabled: true
  commands:
    - "rsync -avz /opt/backups/docker/ user@remote-server:/backup/docker/"
```

### Konfiguration für SQL-Dump-Only Backups

Jede Datenbank kann mit der Option `only_sql_dump` konfiguriert werden:

- `only_sql_dump: false` (Standard): Sichert sowohl den SQL-Dump als auch den Filestore
- `only_sql_dump: true`: Sichert nur den SQL-Dump, überspringt den Filestore

Für SQL-Only-Backups wird der Dateiname mit `_sql_only` ergänzt, um den Inhalt zu kennzeichnen:
- Beispiel: `database_container_dockerbackup_2025-04-09_16-34-50_sql_only.7z`

Diese Option ist besonders nützlich für:
- Datenbanken mit sehr großen Filestores, wo eine regelmäßige Sicherung nur der Datenbank ausreicht
- Temporäre Kopien, bei denen der Filestore nicht benötigt wird
- Situations, in denen häufigere SQL-Dumps, aber seltenere vollständige Backups gewünscht sind

### Kompressionskonfiguration

Die Kompression kann im `defaults`-Bereich konfiguriert werden:

```yaml
defaults:
  compression:
    format: "7z"     # Kompressionsformat: 7z, zip, gzip, zstd
    level: 5         # Kompressionsgrad (0-9, Standard: 5)
```

#### Unterstützte Kompressionsformate

- **7z**: Beste Kompression und einziges Format mit Verschlüsselung
  - Bietet AES-256 Verschlüsselung
  - Benötigt neuere 7-Zip-Version mit dem 7zz-Befehl
  - **Wichtig**: Das alte 7z-Kommando wird nicht mehr unterstützt

- **zip**: Standard-ZIP-Format
  - Bessere Kompatibilität mit anderen Systemen
  - **Keine Verschlüsselung**

- **gzip**: tar.gz Format
  - Gute Kompatibilität
  - **Keine Verschlüsselung**

- **zstd**: tar.zst Format
  - Moderne, schnelle Kompression mit gutem Verhältnis
  - **Keine Verschlüsselung**

#### Kompressionsgrad

Der Kompressionsgrad kann eingestellt werden:
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

**Dateinamensformat:** (abhängig vom Kompressionsformat)
- 7z: `{db_name}_{container}_dockerbackup_{timestamp}.7z`
- ZIP: `{db_name}_{container}_dockerbackup_{timestamp}.zip`
- GZIP: `{db_name}_{container}_dockerbackup_{timestamp}.tar.gz`
- ZSTD: `{db_name}_{container}_dockerbackup_{timestamp}.tar.zst`

**Interne Struktur des Archivs:**
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

**Dateinamensformat:** (abhängig vom Kompressionsformat)
- 7z: `{db_name}_FastReport_{timestamp}.7z`
- ZIP: `{db_name}_FastReport_{timestamp}.zip`
- GZIP: `{db_name}_FastReport_{timestamp}.tar.gz`
- ZSTD: `{db_name}_FastReport_{timestamp}.tar.zst`

**Interne Struktur des Archivs:**
```
/
└── {Original FastReport Verzeichnisstruktur}
```

### 4. Service-Backups

Service-Backups werden in ihren eigenen Unterverzeichnissen gespeichert, mit dem jeweiligen Kompressionsformat als Dateierweiterung.

**Nginx:**
- Dateipfad: `/opt/backups/nginx/nginx_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Enthält: Komplette Nginx-Konfiguration

**Let's Encrypt:**
- Dateipfad: `/opt/backups/letsencrypt/letsencrypt_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Enthält: Let's Encrypt-Zertifikate und -Konfiguration

**Docker-Builds:**
- Dateipfad: `/opt/backups/docker-builds/docker-builds_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Enthält: Docker-Build-Konfigurationen und Dockerfiles

## Verschlüsselung

Die Verschlüsselung ist optional und kann über eine `.env`-Datei aktiviert werden:

1. Erstellen Sie eine `.env`-Datei im selben Verzeichnis wie das Skript:
   ```
   BACKUP_ENCRYPTION_ENABLED=true
   BACKUP_PASSWORD=IhrSicheresPasswort
   ```

2. **Wichtig**: Verschlüsselung wird nur mit dem 7z-Format unterstützt, welches das 7zz-Kommando benötigt.
   - Verschlüsselung wird nur angewendet, wenn das Format in der Konfiguration auf "7z" gesetzt ist
   - Wenn ein anderes Format (zip, gzip, zstd) gewählt wurde, wird die Verschlüsselung ignoriert
   - Das Format in der Konfiguration hat Priorität über die Verschlüsselungseinstellung

## Backup-Prozess

1. Datenbankbackup:
   - SQL-Dump wird aus dem SQL-Container extrahiert
   - Filestore wird aus dem Odoo-Container extrahiert
   - Beide werden in ein Archiv mit dem konfigurierten Format komprimiert

2. FastReport-Backup:
   - Separat vom Datenbankbackup erstellt
   - Direkt vom Host-Dateisystem komprimiert

3. Service-Backups:
   - Nginx, Let's Encrypt, Docker-Builds werden separat gesichert
   - Direkt vom Host-Dateisystem komprimiert

4. Remote-Synchronisation:
   - Optional über rsync-Kommandos konfigurierbar
   - Nach Abschluss aller Backups ausgeführt

## Extraktion von Backups

Je nach verwendetem Kompressionsformat gibt es verschiedene Möglichkeiten, Backups zu extrahieren:

### Vorschau der Inhalte

Bevor Sie ein Backup extrahieren, können Sie den Inhalt anzeigen:

#### 7z-Format (.7z)
```bash
# Mit relativem Pfad
7zz l pfad/zur/backup.7z

# Mit absolutem Pfad
7zz l /opt/backups/docker/datenbank_container_dockerbackup_timestamp.7z

# Mit Passwort (falls verschlüsselt)
7zz l -p"IhrPasswort" pfad/zur/backup.7z
```

#### ZIP-Format (.zip)
```bash
# Mit relativem Pfad
unzip -l pfad/zur/backup.zip

# Mit absolutem Pfad
unzip -l /opt/backups/docker/datenbank_container_dockerbackup_timestamp.zip
```

#### GZIP-Format (.tar.gz)
```bash
# Mit relativem Pfad
tar -tvf pfad/zur/backup.tar.gz

# Mit absolutem Pfad
tar -tvf /opt/backups/docker/datenbank_container_dockerbackup_timestamp.tar.gz
```

#### ZSTD-Format (.tar.zst)
```bash
# Mit relativem Pfad
zstd -l pfad/zur/backup.tar.zst
tar -tvf <(zstd -dc pfad/zur/backup.tar.zst)

# Mit absolutem Pfad
zstd -l /opt/backups/docker/datenbank_container_dockerbackup_timestamp.tar.zst
tar -tvf <(zstd -dc /opt/backups/docker/datenbank_container_dockerbackup_timestamp.tar.zst)
```

### Extraktion der Backups

So extrahieren Sie die Backups in einen Zielordner:

#### 7z-Format (.7z)
```bash
# Mit relativem Pfad
7zz x pfad/zur/backup.7z -ozielordner

# Mit absolutem Pfad
7zz x /opt/backups/docker/datenbank_container_dockerbackup_timestamp.7z -o/pfad/zum/zielordner

# Mit Passwort (falls verschlüsselt)
7zz x pfad/zur/backup.7z -ozielordner -p"IhrPasswort"
```

#### ZIP-Format (.zip)
```bash
# Mit relativem Pfad
unzip pfad/zur/backup.zip -d zielordner

# Mit absolutem Pfad
unzip /opt/backups/docker/datenbank_container_dockerbackup_timestamp.zip -d /pfad/zum/zielordner
```

#### GZIP-Format (.tar.gz)
```bash
# Mit relativem Pfad
mkdir -p zielordner
tar -xzf pfad/zur/backup.tar.gz -C zielordner

# Mit absolutem Pfad
mkdir -p /pfad/zum/zielordner
tar -xzf /opt/backups/docker/datenbank_container_dockerbackup_timestamp.tar.gz -C /pfad/zum/zielordner
```

#### ZSTD-Format (.tar.zst)
```bash
# Mit relativem Pfad
mkdir -p zielordner
tar -I zstd -xf pfad/zur/backup.tar.zst -C zielordner

# Mit absolutem Pfad
mkdir -p /pfad/zum/zielordner
tar -I zstd -xf /opt/backups/docker/datenbank_container_dockerbackup_timestamp.tar.zst -C /pfad/zum/zielordner
```

### Wiederherstellung von Odoo-Datenbank Backups

Bei der Wiederherstellung einer Odoo-Datenbank müssen Sie beachten:

1. Extraktion des Backups in einen temporären Ordner
2. Wiederherstellung des SQL-Dumps
3. Kopieren des Filestore zum korrekten Zielort

Beispiel (für 7z-Format):
```bash
# 1. Backup extrahieren
mkdir -p /tmp/odoo_restore
7zz x /opt/backups/docker/datenbank_container_dockerbackup_timestamp.7z -o/tmp/odoo_restore

# 2. SQL-Dump wiederherstellen
docker exec -i container_name psql -U db_user -d datenbank_name < /tmp/odoo_restore/dump.sql

# 3. Filestore wiederherstellen
docker cp /tmp/odoo_restore/datenbank_name container_name:/opt/odoo/data/filestore/

# 4. Aufräumen
rm -rf /tmp/odoo_restore
```

## Aufräumen alter Backups

- Jeder Backup-Typ kann eine eigene Aufbewahrungsfrist haben (in Tagen)
- Nach Ablauf dieser Frist werden Dateien im entsprechenden Backup-Verzeichnis nach dem jeweiligen Präfix (Datenbankname oder Service-Name) gelöscht
- Die Aufbewahrungsfrist wird für jeden Service und jede Datenbank separat eingestellt
- Achten Sie darauf, keine anderen wichtigen Dateien in den Backup-Verzeichnissen zu speichern, die den gleichen Präfix haben

## Ausführung und Automatisierung

### Kommandozeilenparameter

Das Skript unterstützt folgende Kommandozeilenparameter:

- `--sql-only`: Erzwingt den SQL-Dump-Only-Modus für alle Datenbanken, unabhängig von der Einstellung in der YAML-Datei

Diese Option ist besonders nützlich, wenn das Skript per Cron zu unterschiedlichen Zeiten mit unterschiedlichen Backup-Strategien ausgeführt werden soll:

```bash
# Vollständiges Backup (SQL + Filestore)
/pfad/zu/container2backup.py

# Nur SQL-Dump (schneller, spart Speicherplatz)
/pfad/zu/container2backup.py --sql-only
```

### Automatisierung mit Cron

**Empfohlen:** Nutzen Sie das Helfer-Skript `setup-maintenance-cron.sh`. Es installiert die
Wartungs-Jobs deklarativ als `/etc/cron.d/myodoo-maintenance` (versioniert im Repo) plus eine
passende logrotate-Konfiguration — idempotent und sauber wieder entfernbar.

```bash
# Backup (02:00 + 14:00), Cert-Erneuerung und DSGVO-Weblog-Bereinigung einrichten
sudo /root/setup-maintenance-cron.sh

# Wieder entfernen
sudo /root/setup-maintenance-cron.sh --remove
```

Der installierte Job (Version 4.5.x) sieht so aus:

```cron
# /etc/cron.d/myodoo-maintenance — von setup-maintenance-cron.sh verwaltet
0 2  * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1
0 14 * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1
```

Wichtig zur Umleitung:

- `>> datei 2>&1` hängt **stdout UND stderr** an die Logdatei an. So landen auch Fehler
  (Tracebacks) im Log — anders als bei `| tee datei`, das stderr verwirft.
- `</dev/null` gibt dem Skript einen leeren stdin. container2backup.py erkennt einen
  fehlenden TTY und bricht bei Pfadproblemen sauber ab, statt an einer Rückfrage zu hängen.
- Die Logdateien werden über `/etc/logrotate.d/myodoo-maintenance` wöchentlich rotiert.

Wer lieber eine benutzergebundene Crontab pflegt (`crontab -e`), sollte dieselbe Umleitung
verwenden (`>> … 2>&1`, `</dev/null`) — nicht `| tee`.

**Alt-Einträge in der User-Crontab:** Wer das Skript auf einem Server mit existierenden
Crontab-Einträgen für `container2backup.py`, `ssl-renew.sh`, `cleanup-weblogs.py` oder
`nginx-cert-guard.py` ausführt, bekommt nach der Installation eine Warnung mit den
betroffenen Zeilen — diese würden parallel zum cron.d-Job laufen (z. B. Backup doppelt).
Das Skript editiert die User-Crontab **nie automatisch** (sie kann unverwandte Einträge
enthalten); entfernen lassen sich die Doppler mit `sudo crontab -e -u root`.

---

<a id="english-version"></a>
# English Version

## Overview

This backup system secures Odoo databases, Docker containers, and additional services in compressed archives. It was designed to create complete backups of Odoo installations running in Docker containers.

### Main Features

- Backup of multiple Odoo databases (SQL dump + filestore)
- Backup of FastReport files per database
- Backup of additional services (Nginx, Let's Encrypt, Docker builds)
- Various compression formats with adjustable compression level
- Optional AES-256 encryption (only with 7z format)
- Automatic management of old backups
- Configuration via YAML file

## Installation

1. Install the required packages:
   ```bash
   sudo apt-get install 7zip zstd
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
    format: "7z"     # Compression format: 7z, zip, gzip, zstd
    level: 5         # Compression level (0-9, default: 5)

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
    only_sql_dump: false  # Optional: Back up SQL dump and filestore (default behavior)
    fast_report:
      enabled: true
      path: /opt/fast-report/live

  - name: test_db
    sql_container: test-db
    data_container: test-odoo
    retention_days: 5
    only_sql_dump: true   # Only back up SQL dump, skip filestore
    fast_report:
      enabled: true
      path: /opt/fast-report/test

rsync:
  enabled: true
  commands:
    - "rsync -avz /opt/backups/docker/ user@remote-server:/backup/docker/"
```

### Configuration for SQL Dump Only Backups

Each database can be configured with the `only_sql_dump` option:

- `only_sql_dump: false` (default): Backs up both SQL dump and filestore
- `only_sql_dump: true`: Backs up only the SQL dump, skips the filestore

For SQL-only backups, the filename is appended with `_sql_only` to indicate the content:
- Example: `database_container_dockerbackup_2025-04-09_16-34-50_sql_only.7z`

This option is particularly useful for:
- Databases with very large filestores where regular backup of just the database is sufficient
- Temporary copies where the filestore is not needed
- Situations where more frequent SQL dumps but less frequent full backups are desired

### Compression Configuration

Compression can be configured in the `defaults` section:

```yaml
defaults:
  compression:
    format: "7z"     # Compression format: 7z, zip, gzip, zstd
    level: 5         # Compression level (0-9, default: 5)
```

#### Supported Compression Formats

- **7z**: Best compression and the only format with encryption
  - Provides AES-256 encryption
  - Requires newer 7-Zip version with the 7zz command
  - **Important**: The old 7z command is no longer supported

- **zip**: Standard ZIP format
  - Better compatibility with other systems
  - **No encryption**

- **gzip**: tar.gz format
  - Good compatibility
  - **No encryption**

- **zstd**: tar.zst format
  - Modern, fast compression with good ratio
  - **No encryption**

#### Compression Level

The compression level can be adjusted:
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

**Filename format:** (depends on compression format)
- 7z: `{db_name}_{container}_dockerbackup_{timestamp}.7z`
- ZIP: `{db_name}_{container}_dockerbackup_{timestamp}.zip`
- GZIP: `{db_name}_{container}_dockerbackup_{timestamp}.tar.gz`
- ZSTD: `{db_name}_{container}_dockerbackup_{timestamp}.tar.zst`

**Internal structure of the archive:**
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

**Filename format:** (depends on compression format)
- 7z: `{db_name}_FastReport_{timestamp}.7z`
- ZIP: `{db_name}_FastReport_{timestamp}.zip`
- GZIP: `{db_name}_FastReport_{timestamp}.tar.gz`
- ZSTD: `{db_name}_FastReport_{timestamp}.tar.zst`

**Internal structure of the archive:**
```
/
└── {Original FastReport directory structure}
```

### 4. Service Backups

Service backups are stored in their own subdirectories, with the respective compression format as file extension.

**Nginx:**
- File path: `/opt/backups/nginx/nginx_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Contains: Complete Nginx configuration

**Let's Encrypt:**
- File path: `/opt/backups/letsencrypt/letsencrypt_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Contains: Let's Encrypt certificates and configuration

**Docker Builds:**
- File path: `/opt/backups/docker-builds/docker-builds_{timestamp}.[7z|zip|tar.gz|tar.zst]`
- Contains: Docker build configurations and Dockerfiles

## Encryption

Encryption is optional and can be activated via a `.env` file:

1. Create a `.env` file in the same directory as the script:
   ```
   BACKUP_ENCRYPTION_ENABLED=true
   BACKUP_PASSWORD=YourSecurePassword
   ```

2. **Important**: Encryption is only supported with the 7z format, which requires the 7zz command.
   - Encryption will only be applied if the format in the configuration is set to "7z"
   - If another format (zip, gzip, zstd) is chosen, encryption will be ignored
   - The format in the configuration takes precedence over the encryption setting

## Backup Process

1. Database backup:
   - SQL dump is extracted from the SQL container
   - Filestore is extracted from the Odoo container
   - Both are compressed into an archive with the configured format

2. FastReport backup:
   - Created separately from the database backup
   - Compressed directly from the host file system

3. Service backups:
   - Nginx, Let's Encrypt, Docker builds are backed up separately
   - Compressed directly from the host file system

4. Remote synchronization:
   - Optionally configurable via rsync commands
   - Executed after completion of all backups

## Extracting Backups

Depending on the compression format used, there are different ways to extract backups:

### Previewing Contents

Before extracting a backup, you can preview its contents:

#### 7z Format (.7z)
```bash
# With relative path
7zz l path/to/backup.7z

# With absolute path
7zz l /opt/backups/docker/database_container_dockerbackup_timestamp.7z

# With password (if encrypted)
7zz l -p"YourPassword" path/to/backup.7z
```

#### ZIP Format (.zip)
```bash
# With relative path
unzip -l path/to/backup.zip

# With absolute path
unzip -l /opt/backups/docker/database_container_dockerbackup_timestamp.zip
```

#### GZIP Format (.tar.gz)
```bash
# With relative path
tar -tvf path/to/backup.tar.gz

# With absolute path
tar -tvf /opt/backups/docker/database_container_dockerbackup_timestamp.tar.gz
```

#### ZSTD Format (.tar.zst)
```bash
# With relative path
zstd -l path/to/backup.tar.zst
tar -tvf <(zstd -dc path/to/backup.tar.zst)

# With absolute path
zstd -l /opt/backups/docker/database_container_dockerbackup_timestamp.tar.zst
tar -tvf <(zstd -dc /opt/backups/docker/database_container_dockerbackup_timestamp.tar.zst)
```

### Extracting Backups

To extract backups to a target directory:

#### 7z Format (.7z)
```bash
# With relative path
7zz x path/to/backup.7z -otarget_directory

# With absolute path
7zz x /opt/backups/docker/database_container_dockerbackup_timestamp.7z -o/path/to/target_directory

# With password (if encrypted)
7zz x path/to/backup.7z -otarget_directory -p"YourPassword"
```

#### ZIP Format (.zip)
```bash
# With relative path
unzip path/to/backup.zip -d target_directory

# With absolute path
unzip /opt/backups/docker/database_container_dockerbackup_timestamp.zip -d /path/to/target_directory
```

#### GZIP Format (.tar.gz)
```bash
# With relative path
mkdir -p target_directory
tar -xzf path/to/backup.tar.gz -C target_directory

# With absolute path
mkdir -p /path/to/target_directory
tar -xzf /opt/backups/docker/database_container_dockerbackup_timestamp.tar.gz -C /path/to/target_directory
```

#### ZSTD Format (.tar.zst)
```bash
# With relative path
mkdir -p target_directory
tar -I zstd -xf path/to/backup.tar.zst -C target_directory

# With absolute path
mkdir -p /path/to/target_directory
tar -I zstd -xf /opt/backups/docker/database_container_dockerbackup_timestamp.tar.zst -C /path/to/target_directory
```

### Restoring Odoo Database Backups

When restoring an Odoo database backup, you need to:

1. Extract the backup to a temporary directory
2. Restore the SQL dump
3. Copy the filestore to the correct location

Example (for 7z format):
```bash
# 1. Extract backup
mkdir -p /tmp/odoo_restore
7zz x /opt/backups/docker/database_container_dockerbackup_timestamp.7z -o/tmp/odoo_restore

# 2. Restore SQL dump
docker exec -i container_name psql -U db_user -d database_name < /tmp/odoo_restore/dump.sql

# 3. Restore filestore
docker cp /tmp/odoo_restore/database_name container_name:/opt/odoo/data/filestore/

# 4. Clean up
rm -rf /tmp/odoo_restore
```

## Cleaning up Old Backups

- Each backup type can have its own retention period (in days)
- After this period, files in the corresponding backup directory are deleted according to their prefix (database name or service name)
- The retention period is set separately for each service and database
- Be careful not to store other important files in the backup directories that have the same prefix

## Execution and Automation

### Command Line Parameters

The script supports the following command line parameters:

- `--sql-only`: Forces SQL dump only mode for all databases, regardless of the settings in the YAML file

This option is particularly useful when the script is executed by cron at different times with different backup strategies:

```bash
# Full backup (SQL + filestore)
/path/to/container2backup.py

# SQL dump only (faster, saves disk space)
/path/to/container2backup.py --sql-only
```

### Automation with Cron

**Recommended:** use the helper script `setup-maintenance-cron.sh`. It installs the
maintenance jobs declaratively as `/etc/cron.d/myodoo-maintenance` (versioned in the repo)
plus a matching logrotate config — idempotent and cleanly removable.

```bash
# Install backup (02:00 + 14:00), cert renewal and DSGVO weblog cleanup
sudo /root/setup-maintenance-cron.sh

# Uninstall
sudo /root/setup-maintenance-cron.sh --remove
```

The installed job (version 4.5.x) looks like this:

```cron
# /etc/cron.d/myodoo-maintenance — managed by setup-maintenance-cron.sh
0 2  * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1
0 14 * * * root /root/container2backup.py </dev/null >> /var/log/container2backup.log 2>&1
```

Notes on redirection:

- `>> file 2>&1` appends **both stdout AND stderr** to the log, so failures (tracebacks)
  actually land in the log — unlike `| tee file`, which drops stderr.
- `</dev/null` gives the script an empty stdin. container2backup.py detects the missing TTY
  and aborts cleanly on path issues instead of hanging on a confirmation prompt.
- The log files are rotated weekly via `/etc/logrotate.d/myodoo-maintenance`.

If you prefer a per-user crontab (`crontab -e`), use the same redirection
(`>> … 2>&1`, `</dev/null`) — not `| tee`.

**Legacy entries in the user crontab:** when run on a server that already had crontab
entries for `container2backup.py`, `ssl-renew.sh`, `cleanup-weblogs.py`, or
`nginx-cert-guard.py`, the installer prints a warning listing the offending lines —
those would run alongside the cron.d job (e.g. duplicate backups). The script **never
edits the user crontab automatically** (it may contain unrelated operator entries);
remove the duplicates with `sudo crontab -e -u root`.


