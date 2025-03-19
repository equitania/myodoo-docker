# Odoo Docker Backup Script

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

## Deutsche Version

## Über dieses Skript

Dieses Skript erstellt automatisierte Backups von Odoo-Datenbanken, die in Docker-Containern laufen. Es sichert sowohl die PostgreSQL-Datenbank als auch den FileStore und unterstützt mehrere Odoo-Instanzen.

### Hauptfunktionen

- Backup von mehreren Odoo-Instanzen und Datenbanken
- Unterstützung für verschiedene Kompressionsformate (ZSTD, 7-Zip, ZIP)
- Automatische Verwaltung von alten Backups
- Überwachung des verfügbaren Speicherplatzes
- Fortschrittsanzeige während des Backup-Prozesses
- Backup zusätzlicher Pfade (Nginx, Let's Encrypt, FastReport, usw.)

### Voraussetzungen

1. Python 3.6 oder höher
2. Docker
3. Je nach gewähltem Kompressionsformat:
   - Für ZSTD: `zstd` Paket
   - Für 7-Zip: `p7zip-full` Paket
   - Für ZIP: `zip` und `unzip` Pakete

### Installation

1. Kopieren Sie das Skript `container2backup_enhanced.py` in ein Verzeichnis Ihrer Wahl (z.B. `/opt/scripts/`).
2. Machen Sie das Skript ausführbar:
   ```bash
   chmod +x container2backup_enhanced.py
   ```

### Konfiguration

Das Skript verwendet eine YAML-Konfigurationsdatei. Sie können eine Beispiel-Konfigurationsdatei erstellen mit:

```bash
python3 container2backup_enhanced.py --create-config /pfad/zur/backup_config.yaml
```

#### Konfigurationsbeispiel:

```yaml
backup_root: '/opt/backups'  # Stammverzeichnis für Backups
min_disk_space_gb: 5.0  # Minimaler freier Speicherplatz in GB
compression:
  type: 'zstd'  # Optionen: 'zstd', '7zip', 'zip'
  level: 3  # Kompressionsgrad
default_retention_days: 14  # Aufbewahrungsfrist in Tagen

# Odoo-Instanzen
odoo_instances:
  - name: 'production'
    enabled: true
    databases:
      - name: 'odoo_prod'
        user: 'odoo'
        containers:
          database: 'prod-postgres'  # Name des PostgreSQL-Containers
          odoo: 'prod-odoo'  # Name des Odoo-Containers
        retention_days: 30  # Individuelle Aufbewahrungsfrist

# Zusätzliche Backup-Pfade
additional_backups:
  nginx:
    enabled: true
    source_path: '/etc/nginx'
    retention_days: 14
  fastreport:
    enabled: true
    source_path: '/opt/fastreport'
    retention_days: 14
```

#### Verfügbare Kompressionsformate:

1. **ZSTD** (Standard):
   - Werte: 1-19 (Standard: 3)
   - Schnelle Kompression mit gutem Verhältnis
   - Erfordert installiertes zstd

2. **7-Zip**:
   - Werte: 0-9 (Standard: 5)
   - Beste Kompressionsrate, aber langsamer
   - Erfordert installiertes 7z

3. **ZIP**:
   - Werte: 1-9 (Standard: 6)
   - Höchste Kompatibilität mit anderen Systemen
   - Erfordert installiertes zip/unzip

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

This script creates automated backups of Odoo databases running in Docker containers. It backs up both the PostgreSQL database and the FileStore, and supports multiple Odoo instances.

### Key Features

- Backup of multiple Odoo instances and databases
- Support for different compression formats (ZSTD, 7-Zip, ZIP)
- Automatic management of old backups
- Disk space monitoring
- Progress display during the backup process
- Backup of additional paths (Nginx, Let's Encrypt, FastReport, etc.)

### Requirements

1. Python 3.6 or higher
2. Docker
3. Depending on chosen compression format:
   - For ZSTD: `zstd` package
   - For 7-Zip: `p7zip-full` package
   - For ZIP: `zip` and `unzip` packages

### Installation

1. Copy the script `container2backup_enhanced.py` to a directory of your choice (e.g., `/opt/scripts/`).
2. Make the script executable:
   ```bash
   chmod +x container2backup_enhanced.py
   ```

### Configuration

The script uses a YAML configuration file. You can create a sample configuration file with:

```bash
python3 container2backup_enhanced.py --create-config /path/to/backup_config.yaml
```

#### Configuration Example:

```yaml
backup_root: '/opt/backups'  # Root directory for backups
min_disk_space_gb: 5.0  # Minimum free disk space in GB
compression:
  type: 'zstd'  # Options: 'zstd', '7zip', 'zip'
  level: 3  # Compression level
default_retention_days: 14  # Retention period in days

# Odoo instances
odoo_instances:
  - name: 'production'
    enabled: true
    databases:
      - name: 'odoo_prod'
        user: 'odoo'
        containers:
          database: 'prod-postgres'  # PostgreSQL container name
          odoo: 'prod-odoo'  # Odoo container name
        retention_days: 30  # Individual retention period

# Additional backup paths
additional_backups:
  nginx:
    enabled: true
    source_path: '/etc/nginx'
    retention_days: 14
  fastreport:
    enabled: true
    source_path: '/opt/fastreport'
    retention_days: 14
```

#### Available Compression Formats:

1. **ZSTD** (default):
   - Values: 1-19 (default: 3)
   - Fast compression with good ratio
   - Requires zstd to be installed

2. **7-Zip**:
   - Values: 0-9 (default: 5)
   - Best compression ratio, but slower
   - Requires 7z to be installed

3. **ZIP**:
   - Values: 1-9 (default: 6)
   - Most compatible format
   - Requires zip/unzip to be installed

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