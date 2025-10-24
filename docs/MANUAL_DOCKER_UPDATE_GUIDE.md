# Manuelle Docker Container Update Anleitung für Odoo

## Übersicht

Diese Anleitung beschreibt den manuellen Update-Prozess für Odoo Docker Container, basierend auf dem `update_docker_odoo.py` Script. Sie eignet sich für einzelne Container-Updates oder wenn das automatische Script nicht verfügbar ist.

**Geschätzte Dauer**: 15-50 Minuten (abhängig von Build/Pull und Update-Dauer)

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Beispiel-Konfiguration](#beispiel-konfiguration)
- [Update-Prozess](#update-prozess)
  - [Step 1: Container stoppen und entfernen](#step-1-container-stoppen-und-entfernen)
  - [Step 2: Altes Image entfernen](#step-2-altes-image-entfernen)
  - [Step 3: Neues Image bereitstellen](#step-3-neues-image-bereitstellen)
  - [Step 4: Update durchführen](#step-4-update-durchführen)
  - [Step 5: Container starten](#step-5-container-starten)
  - [Step 6: Verification](#step-6-verification)
  - [Step 7: Cleanup](#step-7-cleanup)
- [DNS-Optimierung](#dns-optimierung)
- [Fehlerbehebung](#fehlerbehebung)
- [Backup und Rollback](#backup-und-rollback)
- [Best Practices](#best-practices)

## Voraussetzungen

### Erforderliche Informationen

Bevor du mit dem Update beginnst, stelle sicher, dass du folgende Informationen hast:

| Parameter | Beschreibung | Beispiel |
|-----------|--------------|----------|
| **Container Name** | Name des Docker Containers | `live-odoo` |
| **Image Name** | Docker Image Name | `odoo/live:latest` |
| **HTTP Port** | HTTP Port Mapping | `11010:8069` |
| **Longpolling Port** | Longpolling Port Mapping | `12010:8072` |
| **Network** | Docker Netzwerk | `live-db-net` |
| **Volume** | Datenpfad | `/home/odoo/opt/odoo/live:/opt/odoo/data` |
| **Database Name** | Odoo Datenbank Name | `live_db` |
| **DB User** | Datenbank Benutzer | `ownerp` |
| **DB Password** | Datenbank Passwort | `ownerp2025` |
| **DB Host** | Datenbank Host/Container | `live-db` |

### Erforderliche Tools

- Docker installiert und verfügbar
- Zugriff auf Dockerfile (für Image Build) oder Docker Registry
- Root/Sudo Rechte für Docker-Befehle
- Genügend Speicherplatz (mindestens 10 GB frei)

### Wichtige Hinweise

⚠️ **WICHTIG**:
- Erstelle vor dem Update immer ein Backup der Datenbank und des Filestores!
- Der Container ist während des Updates nicht erreichbar (Downtime ca. 10-30 Minuten)
- Plane das Update außerhalb der Hauptgeschäftszeiten

## Beispiel-Konfiguration

Für diese Anleitung verwenden wir folgende Beispiel-Konfiguration:

```bash
# Container Configuration
CONTAINER_NAME="live-odoo"
IMAGE_NAME="odoo/live"
HTTP_PORT="11010:8069"
LONGPOLLING_PORT="12010:8072"
NETWORK="live-db-net"
VOLUME="/home/odoo/opt/odoo/live:/opt/odoo/data"

# Database Configuration
DB_NAME="live_db"
DB_USER="ownerp"
DB_PASSWORD="ownerp2025"
DB_HOST="live-db"

# Dockerfile Path (nur für Build erforderlich)
DOCKERFILE_PATH="/home/odoo/dockerfiles/live/"
```

## Update-Prozess

### Step 1: Container stoppen und entfernen

```bash
# Container stoppen
docker stop live-odoo

# Verify container stopped
docker ps --filter name=live-odoo

# Container entfernen
docker rm live-odoo

# Verify container removed
docker ps -a --filter name=live-odoo
```

**Erwartete Ausgabe:**
```
live-odoo
live-odoo
```

**Dauer**: ~10 Sekunden

---

### Step 2: Altes Image entfernen

```bash
# Aktuelles Image anzeigen
docker images | grep odoo/live

# Altes Image entfernen (empfohlen für sauberen Build)
docker rmi odoo/live:latest

# Verify image removed
docker images | grep odoo/live
```

**Optional**: Wenn du das alte Image als Backup behalten möchtest:

```bash
# Image taggen als Backup
docker tag odoo/live:latest odoo/live:backup-$(date +%Y%m%d)

# Dann altes 'latest' Tag entfernen
docker rmi odoo/live:latest
```

**Dauer**: ~5 Sekunden

---

### Step 3: Neues Image bereitstellen

#### Option A: Image von Registry pullen (schneller)

```bash
# Image von Registry pullen
docker pull odoo/live:latest

# Verify image downloaded
docker images | grep odoo/live
```

**Dauer**: 1-5 Minuten (abhängig von Internet-Geschwindigkeit)

#### Option B: Image selbst bauen (für Custom Builds)

```bash
# Zum Dockerfile-Verzeichnis wechseln
cd /home/odoo/dockerfiles/live/

# Verify Dockerfile exists
ls -la Dockerfile

# Image bauen
docker build -t odoo/live .

# Verify image built
docker images | grep odoo/live
```

**Hinweis**: Der Build-Prozess lädt ~977 Module einzeln herunter.

**Dauer**: 10-20 Minuten

#### Option C: Build-Skripte verwenden (falls vorhanden)

```bash
# Zum Dockerfile-Verzeichnis wechseln
cd /home/odoo/dockerfiles/live/

# Download build script (für Odoo v16 Beispiel)
wget -q -N https://rm.ownerp.io/staff/v16-muster/build_odoo.py

# Run build script
python3 build_odoo.py

# Image bauen
docker build -t odoo/live .
```

---

### Step 4: Update durchführen

**WICHTIG**: Der Update-Schritt verwendet einen temporären Container (`--rm` Flag), der nach Abschluss automatisch entfernt wird.

#### Option A: Full Update (Standard)

```bash
# Full Update mit temporärem Container
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo \
  odoo/live:latest \
  update --database=live_db \
         --db_user=ownerp \
         --db_password=ownerp2025 \
         --db_host=live-db
```

**Mit allen Übersetzungen**:

```bash
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo \
  odoo/live:latest \
  update --database=live_db \
         --db_user=ownerp \
         --db_password=ownerp2025 \
         --db_host=live-db \
         --i18n-overwrite \
         --load-language=all
```

**Dauer**: 5-30 Minuten (abhängig von Datenbankgröße und Anzahl der Module)

#### Option B: Neutralize & Update (bei größeren Änderungen)

Verwende diese Option bei:
- Major Version Updates
- Strukturellen Änderungen
- Wenn das normale Update fehlschlägt

```bash
# Schritt 1: Neutralize
echo "=== Neutralizing database ==="
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo \
  odoo/live:latest \
  neutralize --database=live_db \
             --db_user=ownerp \
             --db_password=ownerp2025 \
             --db_host=live-db

# Schritt 2: Update
echo "=== Updating database ==="
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo \
  odoo/live:latest \
  update --database=live_db \
         --db_user=ownerp \
         --db_password=ownerp2025 \
         --db_host=live-db
```

**Dauer**: 10-45 Minuten (Neutralize + Update)

#### Update-Fortschritt überwachen

Der Update-Prozess zeigt Fortschrittsmeldungen an. Typische Ausgaben:

```
2025-06-24 10:30:15,123 1 INFO live_db odoo.modules.loading: loading module sale
2025-06-24 10:30:16,234 1 INFO live_db odoo.modules.loading: Module sale loaded
```

---

### Step 5: Container starten

Nach erfolgreichem Update, starte den Container im Daemon-Modus:

```bash
# Container final starten
docker run -d \
  -p 11010:8069 \
  -p 12010:8072 \
  --restart=always \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name="live-odoo" \
  odoo/live:latest \
  start
```

**Mit DNS-Optimierung** (empfohlen):

```bash
docker run -d \
  -p 11010:8069 \
  -p 12010:8072 \
  --restart=always \
  --network live-db-net \
  --dns 1.1.1.1 \
  --dns 8.8.8.8 \
  --dns 9.9.9.9 \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name="live-odoo" \
  odoo/live:latest \
  start
```

**Verify container started**:

```bash
# Check container status
docker ps --filter name=live-odoo

# Should show:
# CONTAINER ID   IMAGE              COMMAND   CREATED         STATUS         PORTS
# abc123def456   odoo/live:latest   "start"   5 seconds ago   Up 4 seconds   ...
```

**Dauer**: ~5 Sekunden

---

### Step 6: Verification

Warte ca. 30 Sekunden bis der Container vollständig initialisiert ist:

```bash
# Wartezeit mit Countdown
echo "Warte 30 Sekunden auf Container-Initialisierung..."
for i in {30..1}; do
  echo -ne "Verbleibende Zeit: $i Sekunden\r"
  sleep 1
done
echo -e "\nWait completed."
```

**Container-Status prüfen**:

```bash
# Container-Status
docker ps --filter name=live-odoo --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Container-Logs (letzte 50 Zeilen)
docker logs live-odoo --tail 50

# Container-Logs live verfolgen
docker logs -f live-odoo
```

**Erwartete Log-Ausgabe** (nach erfolgreicher Initialisierung):

```
2025-06-24 10:35:00,123 1 INFO ? odoo.service.server: HTTP service (werkzeug) running on 0.0.0.0:8069
2025-06-24 10:35:00,124 1 INFO ? odoo.service.server: HTTP service (werkzeug) running on 0.0.0.0:8072
```

**Web-Interface testen**:

```bash
# HTTP Test
curl -I http://localhost:11010

# Sollte HTTP 200 oder 303 zurückgeben
```

**Dauer**: ~1 Minute

---

### Step 7: Cleanup

```bash
# Dangling Images entfernen
docker image prune -f

# Gestoppte Container entfernen
docker container prune -f

# Ungenutzte Volumes anzeigen (NICHT automatisch löschen!)
docker volume ls -f dangling=true

# Komplettes System Cleanup (optional, vorsichtig!)
docker system prune -f

# Disk Space Check
docker system df
```

**Disk Space vor/nach Cleanup**:

```bash
# Vor Cleanup
docker system df
# TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# Images          15        2         5.5GB     4.2GB (76%)
# Containers      3         1         125MB     100MB (80%)
# Local Volumes   8         2         2.3GB     1.8GB (78%)

# Nach Cleanup
docker system df
# TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# Images          3         2         1.3GB     0B (0%)
# Containers      1         1         25MB      0B (0%)
# Local Volumes   2         2         500MB     0B (0%)
```

**Dauer**: ~30 Sekunden

---

## DNS-Optimierung

Docker Container verwenden standardmäßig Docker's eigenen DNS-Resolver (127.0.0.11), der möglicherweise nicht optimal konfiguriert ist. Dies kann zu Problemen führen, besonders bei Cloud-Provider-Kombinationen (z.B. Hetzner ↔ DigitalOcean).

### Empfohlene DNS-Server

```bash
--dns 1.1.1.1    # Cloudflare (sehr schnell)
--dns 8.8.8.8    # Google (zuverlässig)
--dns 9.9.9.9    # Quad9 (sicherheitsorientiert)
```

### Container mit optimiertem DNS starten

```bash
docker run -d \
  -p 11010:8069 \
  -p 12010:8072 \
  --restart=always \
  --network live-db-net \
  --dns 1.1.1.1 \
  --dns 8.8.8.8 \
  --dns 9.9.9.9 \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name="live-odoo" \
  odoo/live:latest \
  start
```

### DNS innerhalb des Containers testen

```bash
# Container betreten
docker exec -it live-odoo /bin/bash

# DNS-Konfiguration prüfen
cat /etc/resolv.conf

# DNS-Auflösung testen
nslookup google.com
nslookup api.digitalocean.com

# Container verlassen
exit
```

---

## Fehlerbehebung

### Problem: Container startet nicht

**Symptom**: Container stoppt sofort nach dem Start

**Diagnose**:

```bash
# Logs ansehen
docker logs live-odoo

# Container-Inspect
docker inspect live-odoo

# Events anzeigen
docker events --filter container=live-odoo --since 10m
```

**Lösung**:

```bash
# Container interaktiv starten zum Debugging
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo-debug \
  odoo/live:latest \
  /bin/bash

# Im Container manuell starten
# cd /opt/odoo
# ./odoo-bin --config=/etc/odoo/odoo.conf
```

---

### Problem: Update schlägt fehl

**Symptom**: Update bricht mit Fehler ab

**Diagnose**:

```bash
# Update mit verbose Logging
docker run -it --rm \
  -p 11010:8069 \
  -p 12010:8072 \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name=live-odoo \
  odoo/live:latest \
  update --database=live_db \
         --db_user=ownerp \
         --db_password=ownerp2025 \
         --db_host=live-db \
         --log-level=debug
```

**Häufige Fehlerursachen**:

1. **Datenbankverbindung fehlgeschlagen**:
   ```bash
   # Datenbank-Container prüfen
   docker ps --filter name=live-db

   # Verbindung testen
   docker exec -it live-db psql -U ownerp -d live_db -c "SELECT version();"
   ```

2. **Modul-Abhängigkeiten fehlen**:
   ```bash
   # Fehlende Python-Pakete
   # Lösung: Dockerfile anpassen und Image neu bauen
   ```

3. **Disk Space Problem**:
   ```bash
   # Speicherplatz prüfen
   df -h

   # Docker Space prüfen
   docker system df

   # Cleanup durchführen
   docker system prune -a
   ```

---

### Problem: Port bereits belegt

**Symptom**:
```
Error response from daemon: driver failed programming external connectivity:
Bind for 0.0.0.0:11010 failed: port is already allocated
```

**Diagnose**:

```bash
# Prüfe welcher Prozess den Port verwendet
sudo netstat -tulpn | grep 11010

# Oder mit lsof
sudo lsof -i :11010
```

**Lösung**:

```bash
# Alter Container läuft noch - stoppen
docker stop live-odoo
docker rm live-odoo

# Oder anderen Port verwenden
docker run -d -p 11011:8069 -p 12011:8072 ...
```

---

### Problem: Datenbank-Migration fehlgeschlagen

**Symptom**: Fehler während des Updates, Module laden nicht

**Diagnose**:

```bash
# Datenbank-Status prüfen
docker exec -it live-db psql -U ownerp -d live_db -c "\dt"

# Modul-Status in Datenbank prüfen
docker exec -it live-db psql -U ownerp -d live_db -c \
  "SELECT name, state FROM ir_module_module WHERE state != 'uninstalled' ORDER BY name;"
```

**Lösung**:

```bash
# Option 1: Neutralize & Update (siehe Step 4, Option B)

# Option 2: Datenbank-Backup wiederherstellen und erneut versuchen
# (siehe Backup und Rollback Sektion)
```

---

### Problem: Network not found

**Symptom**:
```
Error response from daemon: network live-db-net not found
```

**Lösung**:

```bash
# Netzwerk erstellen
docker network create live-db-net

# Oder bestehendes Netzwerk anzeigen
docker network ls

# Mit richtigem Netzwerk-Namen neu starten
```

---

### Problem: Volume Permission Issues

**Symptom**: Container kann nicht auf Filestore schreiben

**Diagnose**:

```bash
# Volume Permissions prüfen
ls -la /home/odoo/opt/odoo/live/

# Container User-ID prüfen
docker exec -it live-odoo id
```

**Lösung**:

```bash
# Permissions korrigieren (Odoo läuft meist als UID 101)
sudo chown -R 101:101 /home/odoo/opt/odoo/live/

# Oder wenn Container als root läuft
sudo chown -R root:root /home/odoo/opt/odoo/live/
```

---

## Backup und Rollback

### Pre-Update Backup erstellen

**WICHTIG**: Immer vor einem Update!

```bash
# Backup-Verzeichnis erstellen
BACKUP_DIR="/home/backup/odoo/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

# Datenbank-Backup
docker exec live-db pg_dump -U ownerp -d live_db -F c -f /tmp/live_db.dump
docker cp live-db:/tmp/live_db.dump $BACKUP_DIR/

# Filestore-Backup
sudo tar -czf $BACKUP_DIR/filestore.tar.gz /home/odoo/opt/odoo/live/filestore/

# Aktuelle Container-Konfiguration speichern
docker inspect live-odoo > $BACKUP_DIR/container_config.json

# Image als Backup taggen
docker tag odoo/live:latest odoo/live:backup-$(date +%Y%m%d)

echo "Backup erstellt in: $BACKUP_DIR"
ls -lh $BACKUP_DIR
```

### Automatisches Backup-Script

```bash
#!/bin/bash
# backup_odoo.sh

CONTAINER_NAME="live-odoo"
DB_CONTAINER="live-db"
DB_NAME="live_db"
DB_USER="ownerp"
FILESTORE_PATH="/home/odoo/opt/odoo/live/filestore/"
BACKUP_BASE="/home/backup/odoo"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE/$TIMESTAMP"

echo "Creating backup directory: $BACKUP_DIR"
mkdir -p $BACKUP_DIR

echo "Backing up database: $DB_NAME"
docker exec $DB_CONTAINER pg_dump -U $DB_USER -d $DB_NAME -F c -f /tmp/${DB_NAME}.dump
docker cp $DB_CONTAINER:/tmp/${DB_NAME}.dump $BACKUP_DIR/
docker exec $DB_CONTAINER rm /tmp/${DB_NAME}.dump

echo "Backing up filestore"
tar -czf $BACKUP_DIR/filestore.tar.gz $FILESTORE_PATH

echo "Saving container configuration"
docker inspect $CONTAINER_NAME > $BACKUP_DIR/container_config.json

echo "Tagging current image as backup"
docker tag odoo/live:latest odoo/live:backup-$TIMESTAMP

echo "Backup completed: $BACKUP_DIR"
ls -lh $BACKUP_DIR
```

**Verwendung**:

```bash
chmod +x backup_odoo.sh
./backup_odoo.sh
```

---

### Rollback durchführen

Falls das Update fehlschlägt oder Probleme verursacht:

```bash
# Container stoppen und entfernen
docker stop live-odoo
docker rm live-odoo

# Backup-Image wiederherstellen
docker tag odoo/live:backup-20250624 odoo/live:latest

# Container mit altem Image starten
docker run -d \
  -p 11010:8069 \
  -p 12010:8072 \
  --restart=always \
  --network live-db-net \
  -v /home/odoo/opt/odoo/live:/opt/odoo/data \
  --name="live-odoo" \
  odoo/live:latest \
  start

# Datenbank wiederherstellen (falls nötig)
BACKUP_DIR="/home/backup/odoo/20250624_103000"
docker cp $BACKUP_DIR/live_db.dump live-db:/tmp/
docker exec live-db pg_restore -U ownerp -d postgres -c -C /tmp/live_db.dump

# Filestore wiederherstellen (falls nötig)
sudo rm -rf /home/odoo/opt/odoo/live/filestore/
sudo tar -xzf $BACKUP_DIR/filestore.tar.gz -C /
```

---

## Best Practices

### Vor dem Update

1. ✅ **Backup erstellen** (Datenbank + Filestore)
2. ✅ **Downtime kommunizieren** an Benutzer
3. ✅ **Testumgebung** vorbereiten (falls vorhanden)
4. ✅ **Speicherplatz prüfen** (mindestens 10 GB frei)
5. ✅ **Changelog lesen** für Breaking Changes
6. ✅ **Update außerhalb der Geschäftszeiten** planen

### Während des Updates

1. ✅ **Logs überwachen** (`docker logs -f live-odoo`)
2. ✅ **Keine weiteren Änderungen** vornehmen
3. ✅ **Update nicht unterbrechen** (außer bei kritischen Fehlern)
4. ✅ **Timeout beachten** (bei großen DBs 30+ Minuten normal)

### Nach dem Update

1. ✅ **Funktionstest durchführen**
   - Login testen
   - Wichtige Module/Views öffnen
   - Berechtigungen prüfen
   - Reports testen
2. ✅ **Performance prüfen**
   - Ladezeiten vergleichen
   - CPU/Memory Usage überwachen
3. ✅ **Logs auf Fehler prüfen**
   ```bash
   docker logs live-odoo | grep -i error
   docker logs live-odoo | grep -i warning
   ```
4. ✅ **Backup aufbewahren** (mindestens 7 Tage)
5. ✅ **Dokumentation aktualisieren**

### Regelmäßige Wartung

```bash
# Wöchentlich: Docker Cleanup
docker system prune -f

# Monatlich: Image Updates prüfen
docker pull odoo/live:latest

# Quartalsweise: Major Updates planen
# Jährlich: Datenbankgröße optimieren
```

---

## Zeitplan und Checkliste

### Kompletter Update-Zeitplan

| Phase | Schritt | Dauer | Kumulativ |
|-------|---------|-------|-----------|
| **Vorbereitung** | Backup erstellen | 5-10 min | 5-10 min |
| **Stop** | Container stoppen & entfernen | 30 sec | 5-11 min |
| **Image** | Image entfernen | 5 sec | 5-11 min |
| **Build/Pull** | Neues Image bereitstellen | 1-20 min | 6-31 min |
| **Update** | Datenbank Update | 5-30 min | 11-61 min |
| **Start** | Container starten | 5 sec | 11-61 min |
| **Verify** | Initialisierung warten | 30 sec | 12-62 min |
| **Test** | Funktionstest | 3-5 min | 15-67 min |
| **Cleanup** | Docker Cleanup | 30 sec | 15-68 min |

**Gesamtdauer**: 15-70 Minuten

### Update-Checkliste

#### Pre-Update (15 Minuten vor Start)

- [ ] Benutzer über Wartungsfenster informiert
- [ ] Backup von Datenbank erstellt
- [ ] Backup von Filestore erstellt
- [ ] Image als Backup getaggt
- [ ] Speicherplatz geprüft (>10 GB frei)
- [ ] Docker läuft ohne Fehler
- [ ] Datenbankverbindung getestet

#### Update-Durchführung

- [ ] Container gestoppt und entfernt
- [ ] Altes Image entfernt
- [ ] Neues Image bereitgestellt (Build/Pull)
- [ ] Update-Befehl ausgeführt
- [ ] Update erfolgreich abgeschlossen (keine Errors)
- [ ] Container im Daemon-Modus gestartet
- [ ] 30 Sekunden Wartezeit eingehalten

#### Post-Update Verification

- [ ] Container läuft (`docker ps`)
- [ ] Logs zeigen keine Errors
- [ ] Web-Interface erreichbar (HTTP 200)
- [ ] Login funktioniert
- [ ] Hauptmodule öffnen sich
- [ ] Reports generieren sich
- [ ] Performance ist akzeptabel
- [ ] Docker Cleanup durchgeführt

#### Bei Problemen

- [ ] Fehler in Logs identifiziert
- [ ] Rollback-Entscheidung getroffen (wenn nötig)
- [ ] Backup wiederhergestellt (wenn nötig)
- [ ] Fehler dokumentiert
- [ ] Support kontaktiert (wenn nötig)

---

## Anhang

### Vollständiges Update-Script

Komplettes Bash-Script für automatisierten Update-Prozess:

```bash
#!/bin/bash
# complete_update.sh
# Komplettes Update-Script für Odoo Docker Container

set -e  # Exit on error

# ============================================================================
# CONFIGURATION
# ============================================================================

CONTAINER_NAME="live-odoo"
IMAGE_NAME="odoo/live"
HTTP_PORT="11010:8069"
LONGPOLLING_PORT="12010:8072"
NETWORK="live-db-net"
VOLUME="/home/odoo/opt/odoo/live:/opt/odoo/data"
DB_NAME="live_db"
DB_USER="ownerp"
DB_PASSWORD="ownerp2025"
DB_HOST="live-db"
DOCKERFILE_PATH="/home/odoo/dockerfiles/live/"
BACKUP_BASE="/home/backup/odoo"

# ============================================================================
# FUNCTIONS
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
    exit 1
}

# ============================================================================
# PRE-UPDATE CHECKS
# ============================================================================

log "Starting pre-update checks..."

# Check if running as root/sudo
if [ "$EUID" -ne 0 ]; then
    error "Please run as root or with sudo"
fi

# Check disk space
AVAILABLE_SPACE=$(df / | tail -1 | awk '{print $4}')
if [ "$AVAILABLE_SPACE" -lt 10485760 ]; then  # 10 GB in KB
    error "Insufficient disk space. Need at least 10 GB free."
fi

# Check if docker is running
if ! docker info > /dev/null 2>&1; then
    error "Docker is not running"
fi

log "Pre-update checks passed"

# ============================================================================
# BACKUP
# ============================================================================

log "Creating backup..."

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE/$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

# Database backup
log "Backing up database: $DB_NAME"
docker exec $DB_HOST pg_dump -U $DB_USER -d $DB_NAME -F c -f /tmp/${DB_NAME}.dump
docker cp $DB_HOST:/tmp/${DB_NAME}.dump $BACKUP_DIR/
docker exec $DB_HOST rm /tmp/${DB_NAME}.dump

# Filestore backup
log "Backing up filestore"
tar -czf $BACKUP_DIR/filestore.tar.gz /home/odoo/opt/odoo/live/filestore/

# Container config backup
log "Saving container configuration"
docker inspect $CONTAINER_NAME > $BACKUP_DIR/container_config.json

# Tag current image
log "Tagging current image as backup"
docker tag ${IMAGE_NAME}:latest ${IMAGE_NAME}:backup-$TIMESTAMP

log "Backup completed: $BACKUP_DIR"

# ============================================================================
# STOP AND REMOVE CONTAINER
# ============================================================================

log "Stopping container: $CONTAINER_NAME"
docker stop $CONTAINER_NAME || true

log "Removing container: $CONTAINER_NAME"
docker rm $CONTAINER_NAME || true

# ============================================================================
# REMOVE OLD IMAGE
# ============================================================================

log "Removing old image: ${IMAGE_NAME}:latest"
docker rmi ${IMAGE_NAME}:latest || true

# ============================================================================
# BUILD NEW IMAGE
# ============================================================================

log "Building new image..."
cd "$DOCKERFILE_PATH"

if [ ! -f "Dockerfile" ]; then
    error "Dockerfile not found in $DOCKERFILE_PATH"
fi

log "Building image: ${IMAGE_NAME}"
docker build -t ${IMAGE_NAME} . || error "Image build failed"

log "Image built successfully"

# ============================================================================
# UPDATE DATABASE
# ============================================================================

log "Starting database update..."

docker run -it --rm \
  -p $HTTP_PORT \
  -p $LONGPOLLING_PORT \
  --network $NETWORK \
  -v $VOLUME \
  --name=$CONTAINER_NAME \
  ${IMAGE_NAME}:latest \
  update --database=$DB_NAME \
         --db_user=$DB_USER \
         --db_password=$DB_PASSWORD \
         --db_host=$DB_HOST

if [ $? -ne 0 ]; then
    error "Database update failed. Rolling back..."
    # Rollback would be implemented here
fi

log "Database update completed successfully"

# ============================================================================
# START CONTAINER
# ============================================================================

log "Starting container: $CONTAINER_NAME"

docker run -d \
  -p $HTTP_PORT \
  -p $LONGPOLLING_PORT \
  --restart=always \
  --network $NETWORK \
  --dns 1.1.1.1 \
  --dns 8.8.8.8 \
  --dns 9.9.9.9 \
  -v $VOLUME \
  --name="$CONTAINER_NAME" \
  ${IMAGE_NAME}:latest \
  start

if [ $? -ne 0 ]; then
    error "Failed to start container"
fi

log "Container started successfully"

# ============================================================================
# WAIT FOR INITIALIZATION
# ============================================================================

log "Waiting 30 seconds for container initialization..."
for i in {30..1}; do
    echo -ne "Remaining: $i seconds\r"
    sleep 1
done
echo ""

# ============================================================================
# VERIFICATION
# ============================================================================

log "Verifying container status..."

if docker ps --filter name=$CONTAINER_NAME | grep -q $CONTAINER_NAME; then
    log "Container is running"
else
    error "Container is not running"
fi

# Check logs for errors
log "Checking logs for errors..."
ERROR_COUNT=$(docker logs $CONTAINER_NAME 2>&1 | grep -i error | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
    log "WARNING: Found $ERROR_COUNT error messages in logs"
    docker logs $CONTAINER_NAME 2>&1 | grep -i error | tail -10
fi

# ============================================================================
# CLEANUP
# ============================================================================

log "Running Docker cleanup..."
docker system prune -f

# ============================================================================
# SUMMARY
# ============================================================================

log "============================================"
log "UPDATE COMPLETED SUCCESSFULLY"
log "============================================"
log "Container: $CONTAINER_NAME"
log "Image: ${IMAGE_NAME}:latest"
log "Database: $DB_NAME"
log "Backup: $BACKUP_DIR"
log "============================================"
log "Please verify the application is working correctly"
log "Backup will be kept for 7 days"
log "============================================"

exit 0
```

**Verwendung**:

```bash
# Script ausführbar machen
chmod +x complete_update.sh

# Mit sudo ausführen
sudo ./complete_update.sh

# Logs in Datei speichern
sudo ./complete_update.sh 2>&1 | tee update_$(date +%Y%m%d_%H%M%S).log
```

---

## Kontakt und Support

Bei Problemen oder Fragen:

- **Equitania Software GmbH**: https://www.equitania.de
- **GitHub Issues**: https://github.com/equitania/myodoo-docker/issues
- **Documentation**: https://github.com/equitania/myodoo-docker

---

## Changelog

| Version | Datum | Änderungen |
|---------|-------|------------|
| 1.0.0 | 24.06.2025 | Initiale Version der Anleitung |

---

**Hinweis**: Diese Anleitung basiert auf `update_docker_odoo.py` Version 5.1.6 vom 15.07.2025.
