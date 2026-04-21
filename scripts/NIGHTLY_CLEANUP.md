# nightly-cleanup.sh

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Projektbeschreibung

Speicherbasiertes Docker-Container-Management-Skript, das Container **nur dann** neu startet, wenn sie einen konfigurierbaren RAM-Schwellenwert uberschreiten. Im Gegensatz zu blinden Nightly-Restart-Skripten werden gesunde Container nicht angetastet.

**Maintainer**: Equitania Software GmbH — info@ownerp.com

### Funktionsweise

```
1. Systemstatus erfassen (RAM, Swap, Docker-Disk)
2. Speicherauslastung aller Container pruefen
3. Docker Image/Build-Cache bereinigen (dangling only)
4. Container-Gruppen pruefen und bei Bedarf neu starten:
   a. FastReport — unabhaengig, einzeln
   b. Odoo + Postgres — geordneter Neustart als Gruppe
   c. Sonstige — einzeln
5. OS-Bereinigung (Page Cache, Swap, Journal)
6. Vorher/Nachher-Vergleich ins Log schreiben
```

### Neustart-Reihenfolge (Odoo/Postgres-Gruppe)

Wenn **ein** Container der Odoo/Postgres-Gruppe den Schwellenwert ueberschreitet, wird die **gesamte Gruppe** geordnet neugestartet:

```
Odoo stoppen → Postgres neustarten → pg_isready abwarten → Odoo starten
```

### Installation

```bash
# Skript nach /usr/local/bin kopieren
sudo cp scripts/nightly-cleanup.sh /usr/local/bin/nightly-cleanup.sh
sudo chmod +x /usr/local/bin/nightly-cleanup.sh

# Cronjob einrichten (taeglich um 3:00 Uhr)
echo "0 3 * * * root /usr/local/bin/nightly-cleanup.sh" | sudo tee /etc/cron.d/nightly-cleanup
```

### Verwendung

```bash
# Normaler Lauf (Standard-Schwellenwert: 80%)
/usr/local/bin/nightly-cleanup.sh

# Schwellenwert anpassen (z.B. 90%)
MEMORY_THRESHOLD=90 /usr/local/bin/nightly-cleanup.sh

# Trockenlauf — nur pruefen, nichts neustarten
DRY_RUN=1 /usr/local/bin/nightly-cleanup.sh

# Eigenes Log-Verzeichnis
CLEANUP_LOG=/var/log/custom-cleanup.log /usr/local/bin/nightly-cleanup.sh

# Container-Muster anpassen
ODOO_PATTERN="odoo|myodoo" POSTGRES_PATTERN="live-db|test-db" /usr/local/bin/nightly-cleanup.sh
```

### Konfiguration

Alle Einstellungen erfolgen ueber Umgebungsvariablen:

| Variable | Standard | Beschreibung |
|----------|----------|--------------|
| `MEMORY_THRESHOLD` | `80` | RAM-Schwellenwert in Prozent |
| `CLEANUP_LOG` | `/var/log/nightly-cleanup.log` | Log-Datei-Pfad |
| `DRY_RUN` | `0` | `1` = nur pruefen, nicht neustarten |
| `ODOO_PATTERN` | `odoo` | grep-Pattern fuer Odoo-Container |
| `POSTGRES_PATTERN` | `postgres\|psql\|pg-\|db-\|-db` | grep-Pattern fuer Postgres-Container |
| `FASTREPORT_PATTERN` | `fastreport\|fast-report\|report` | grep-Pattern fuer FastReport-Container |
| `JOURNAL_RETENTION` | `7d` | Journal-Log-Aufbewahrungsdauer |

### Log-Ausgabe (Beispiel)

```
────────────────────────────────────────────────────────
2026-03-17 03:00:01 | Nightly cleanup started (threshold: 80%, dry_run: 0)
────────────────────────────────────────────────────────

────────────────────────────────────────────────────────
2026-03-17 03:00:02 | [MEMORY CHECK] Checking container memory usage
────────────────────────────────────────────────────────
2026-03-17 03:00:03 |   OVER  live-odoo: 2.1GiB / 2.5GiB (84.00%) > 80%
2026-03-17 03:00:04 |   OK    live-db: 512MiB / 2GiB (25.00%) <= 80%
2026-03-17 03:00:05 |   OK    nginx: 45MiB / 512MiB (8.79%) <= 80%

────────────────────────────────────────────────────────
2026-03-17 03:00:15 | [COMPARISON] Before -> After
────────────────────────────────────────────────────────
2026-03-17 03:00:15 |   RAM used:        3200 MB -> 2100 MB (1100 MB freed)
2026-03-17 03:00:15 |   Containers restarted: 2
```

### Sicherheitsmerkmale

- `set -euo pipefail` — Fehler werden sofort erkannt
- Alle Variablen gequotet — kein Word-Splitting
- `drop_caches=1` (nur Page Cache) statt `3` (aggressiv)
- Swap-Reset nur wenn genuegend freier RAM vorhanden
- Absichtlich gestoppte Container werden nicht angetastet
- Dry-Run-Modus fuer sichere Vorab-Pruefung

---

## English Documentation

### Project Description

Memory-based Docker container management script that **only** restarts containers exceeding a configurable RAM threshold. Unlike blind nightly restart scripts, healthy containers are left untouched.

**Maintainer**: Equitania Software GmbH — info@ownerp.com

### How It Works

```
1. Capture system state (RAM, swap, Docker disk)
2. Check memory usage of all running containers
3. Prune Docker images/build cache (dangling only)
4. Check container groups and restart if needed:
   a. FastReport — independent, individual
   b. Odoo + Postgres — ordered group restart
   c. Others — individual
5. OS cleanup (page cache, swap, journal)
6. Write before/after comparison to log
```

### Restart Order (Odoo/Postgres Group)

When **any** container in the Odoo/Postgres group exceeds the threshold, the **entire group** is restarted in order:

```
Stop Odoo → Restart Postgres → wait pg_isready → Start Odoo
```

### Installation

```bash
# Copy script to /usr/local/bin
sudo cp scripts/nightly-cleanup.sh /usr/local/bin/nightly-cleanup.sh
sudo chmod +x /usr/local/bin/nightly-cleanup.sh

# Set up cron job (daily at 3:00 AM)
echo "0 3 * * * root /usr/local/bin/nightly-cleanup.sh" | sudo tee /etc/cron.d/nightly-cleanup
```

### Usage

```bash
# Normal run (default threshold: 80%)
/usr/local/bin/nightly-cleanup.sh

# Custom threshold (e.g. 90%)
MEMORY_THRESHOLD=90 /usr/local/bin/nightly-cleanup.sh

# Dry run — check only, no restarts
DRY_RUN=1 /usr/local/bin/nightly-cleanup.sh

# Custom log location
CLEANUP_LOG=/var/log/custom-cleanup.log /usr/local/bin/nightly-cleanup.sh

# Custom container patterns
ODOO_PATTERN="odoo|myodoo" POSTGRES_PATTERN="live-db|test-db" /usr/local/bin/nightly-cleanup.sh
```

### Configuration

All settings are controlled via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_THRESHOLD` | `80` | RAM threshold in percent |
| `CLEANUP_LOG` | `/var/log/nightly-cleanup.log` | Log file path |
| `DRY_RUN` | `0` | `1` = check only, no restarts |
| `ODOO_PATTERN` | `odoo` | grep pattern for Odoo containers |
| `POSTGRES_PATTERN` | `postgres\|psql\|pg-\|db-\|-db` | grep pattern for Postgres containers |
| `FASTREPORT_PATTERN` | `fastreport\|fast-report\|report` | grep pattern for FastReport containers |
| `JOURNAL_RETENTION` | `7d` | Journal log retention period |

### Log Output (Example)

```
────────────────────────────────────────────────────────
2026-03-17 03:00:01 | Nightly cleanup started (threshold: 80%, dry_run: 0)
────────────────────────────────────────────────────────

────────────────────────────────────────────────────────
2026-03-17 03:00:02 | [MEMORY CHECK] Checking container memory usage
────────────────────────────────────────────────────────
2026-03-17 03:00:03 |   OVER  live-odoo: 2.1GiB / 2.5GiB (84.00%) > 80%
2026-03-17 03:00:04 |   OK    live-db: 512MiB / 2GiB (25.00%) <= 80%
2026-03-17 03:00:05 |   OK    nginx: 45MiB / 512MiB (8.79%) <= 80%

────────────────────────────────────────────────────────
2026-03-17 03:00:15 | [COMPARISON] Before -> After
────────────────────────────────────────────────────────
2026-03-17 03:00:15 |   RAM used:        3200 MB -> 2100 MB (1100 MB freed)
2026-03-17 03:00:15 |   Containers restarted: 2
```

### Safety Features

- `set -euo pipefail` — immediate error detection
- All variables quoted — no word splitting
- `drop_caches=1` (page cache only) instead of `3` (aggressive)
- Swap reset only when enough free RAM is available
- Intentionally stopped containers are not touched
- Dry-run mode for safe pre-flight checks

### Workflow Diagram

```
Start
  |
  v
[Capture BEFORE state]
  |
  v
[Check memory usage of ALL containers]
  |
  v
[Prune dangling images + build cache]
  |
  +---> [FastReport: over threshold?] --yes--> restart individually
  |                                    --no---> skip
  |
  +---> [Odoo/PG group: ANY over threshold?]
  |       |
  |      yes --> Stop Odoo → Restart Postgres → pg_isready → Start Odoo
  |       |
  |      no ---> skip entire group
  |
  +---> [Other containers: over threshold?] --yes--> restart individually
  |                                          --no---> skip
  |
  v
[OS cleanup: page cache, swap, journal]
  |
  v
[Capture AFTER state]
  |
  v
[Log BEFORE vs AFTER comparison]
  |
  v
Done
```
