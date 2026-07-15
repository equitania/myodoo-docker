# PostgreSQL Local Deploy (pg-local-deploy.sh)

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

## Übersicht

`pg-local-deploy.sh` (v1.2.0) ist ein interaktives On-Premise-Deploy-Skript für PostgreSQL-Docker-Container. Es spiegelt das Ansible-Playbook `semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml` auf der lokalen Maschine, damit PostgreSQL-Instanzen auch ohne Semaphore/Ansible-Setup (z.B. Kunden-On-Premise) ausgerollt werden können.

### Hauptfunktionen

- Interaktive Abfrage aller Parameter (Container-Name, Verzeichnisse, User, Passwort, Version)
- Vier eingebettete PostgreSQL-Conf-Profile (1:1 aus der Ansible-Produktion):
  `2cpu4gb`, `2cpu8gb`, `4cpu16gb`, `8cpu32gb`
- Optionales Self-Signed-SSL (Opt-in) — Odoo mit `db_sslmode = prefer` nutzt TLS dann automatisch
- Docker-Compose-File wird generiert (Steuerung auch ohne Compose via `docker run` möglich)
- Ablauf wie im Playbook: initdb → pg_isready → Conf einspielen → Neustart → Verifikation
- Self-contained: eine einzelne Datei, keine Secrets im Skript, Passwort-Abfrage silent mit Wiederholung

## Voraussetzungen

- Docker (Daemon erreichbar); `docker compose` oder `docker-compose` optional
- Schreibrechte im Basis-Verzeichnis (Default `/opt/postgresql`), ggf. via sudo

## Verwendung

```bash
./pg-local-deploy.sh
```

Das Skript fragt interaktiv ab:

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| Container-Name | `live-db` | Name des PostgreSQL-Containers |
| Basis-Verzeichnis | `/opt/postgresql` | Ablage für PGDATA und Deploy-Dateien |
| DB-User | `ownerp` | PostgreSQL-Superuser (initdb) |
| DB-Name | `postgres` | Initiale Datenbank |
| Passwort | — (Pflicht) | Silent-Eingabe mit Wiederholung |
| PostgreSQL-Version | — (Pflicht) | z.B. `16.14` → Image `postgres:16.14` ([verfügbare Tags](https://hub.docker.com/_/postgres/tags?name=16.)) |
| Conf-Profil | `2cpu8gb` | Hardware-Profil (siehe oben) |
| Host-Port | keiner | Optionales Publish auf `127.0.0.1` |
| SSL | `nein` | Self-Signed-SSL aktivieren (y/N) |

### Volume-Layout

```
{base}/{name}          → PGDATA (999:999, 0700)
{base}/{name}-deploy/  → docker-compose.yml + postgresql.conf.src
```

## Self-Signed-SSL (optional)

Bei Aktivierung (`y` bei der SSL-Abfrage):

- An die extrahierte `postgresql.conf.src` wird ein markierter Override-Block angehängt (`ssl = on`); die eingebetteten Ansible-Profile bleiben unverändert.
- Beim Conf-Einspielen wird im Postgres-Container per `openssl` ein Self-Signed-Zertifikat erzeugt: RSA 4096, 10 Jahre gültig, `CN = <Container-Name>`, abgelegt als `server.crt`/`server.key` in PGDATA (PostgreSQL-Standardpfade, Key 0600 / 999:999).
- Idempotent: Ein vorhandenes Zertifikat wird bei Re-Runs nicht überschrieben.
- Die Verifikation prüft `SHOW ssl;` = `on`.

**Hinweise:**

- Odoo-Container mit `db_sslmode = prefer` verschlüsseln die Verbindung automatisch, sobald der Server SSL anbietet — keine Odoo-Änderung nötig.
- Das Zertifikat ist self-signed: Client-Modi mit Zertifikatsprüfung (`verify-ca`/`verify-full`) funktionieren damit nicht.
- Zertifikat manuell erneuern: `server.crt`/`server.key` in PGDATA löschen und das Deploy-Skript erneut ausführen.

## Betrieb

```bash
docker compose -f {base}/{name}-deploy/docker-compose.yml logs -f   # Logs
docker compose -f {base}/{name}-deploy/docker-compose.yml stop     # Anhalten
docker compose -f {base}/{name}-deploy/docker-compose.yml start    # Starten
docker compose -f {base}/{name}-deploy/docker-compose.yml down     # Entfernen (PGDATA bleibt)
```

Odoo-Container an die Datenbank anbinden (DB-Host = Container-Name, Port 5432):

```bash
docker network connect {name}-net <odoo-container>
```

## Fehlerbehebung

- **Container startet nach Conf-Update nicht:** `docker logs <name>` prüfen; Rollback durch Zurückkopieren von `postgresql.conf.bak-<timestamp>` in PGDATA.
- **`SHOW ssl` liefert nicht `on`:** Logs prüfen — meist fehlen `server.crt`/`server.key` in PGDATA oder die Rechte stimmen nicht (Key muss 0600, Owner 999:999 sein).
- **Passwort greift nicht:** `POSTGRES_PASSWORD` wirkt nur beim ersten Start (initdb). Bei bestehendem PGDATA das Passwort in der Datenbank ändern.

---

<a id="english-version"></a>
# English Version

## Overview

`pg-local-deploy.sh` (v1.2.0) is an interactive on-premise deploy script for PostgreSQL Docker containers. It mirrors the Ansible playbook `semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml` on the local machine so PostgreSQL instances can be rolled out without a Semaphore/Ansible setup (e.g. customer on-premise).

### Key Features

- Interactive prompts for all parameters (container name, directories, user, password, version)
- Four embedded PostgreSQL conf profiles (1:1 copies from Ansible production):
  `2cpu4gb`, `2cpu8gb`, `4cpu16gb`, `8cpu32gb`
- Optional self-signed SSL (opt-in) — Odoo with `db_sslmode = prefer` uses TLS automatically
- Generates a Docker Compose file (also controllable without Compose via `docker run`)
- Playbook-identical flow: initdb → pg_isready → install conf → restart → verification
- Self-contained: a single file, no secrets in the script, silent password prompt with confirmation

## Prerequisites

- Docker (daemon reachable); `docker compose` or `docker-compose` optional
- Write access to the base directory (default `/opt/postgresql`), via sudo if needed

## Usage

```bash
./pg-local-deploy.sh
```

The script prompts interactively:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Container name | `live-db` | Name of the PostgreSQL container |
| Base directory | `/opt/postgresql` | Location for PGDATA and deploy files |
| DB user | `ownerp` | PostgreSQL superuser (initdb) |
| DB name | `postgres` | Initial database |
| Password | — (required) | Silent input with confirmation |
| PostgreSQL version | — (required) | e.g. `16.14` → image `postgres:16.14` ([available tags](https://hub.docker.com/_/postgres/tags?name=16.)) |
| Conf profile | `2cpu8gb` | Hardware profile (see above) |
| Host port | none | Optional publish on `127.0.0.1` |
| SSL | `no` | Enable self-signed SSL (y/N) |

### Volume Layout

```
{base}/{name}          → PGDATA (999:999, 0700)
{base}/{name}-deploy/  → docker-compose.yml + postgresql.conf.src
```

## Self-Signed SSL (optional)

When enabled (`y` at the SSL prompt):

- A marked override block (`ssl = on`) is appended to the extracted `postgresql.conf.src`; the embedded Ansible profiles remain untouched.
- During conf installation a self-signed certificate is generated inside the postgres container via `openssl`: RSA 4096, valid 10 years, `CN = <container name>`, stored as `server.crt`/`server.key` in PGDATA (PostgreSQL default paths, key 0600 / 999:999).
- Idempotent: an existing certificate is kept on re-runs.
- Verification checks `SHOW ssl;` = `on`.

**Notes:**

- Odoo containers with `db_sslmode = prefer` encrypt the connection automatically as soon as the server offers SSL — no Odoo change required.
- The certificate is self-signed: client modes with certificate verification (`verify-ca`/`verify-full`) will not work with it.
- To renew the certificate manually: delete `server.crt`/`server.key` in PGDATA and re-run the deploy script.

## Operations

```bash
docker compose -f {base}/{name}-deploy/docker-compose.yml logs -f   # logs
docker compose -f {base}/{name}-deploy/docker-compose.yml stop     # stop
docker compose -f {base}/{name}-deploy/docker-compose.yml start    # start
docker compose -f {base}/{name}-deploy/docker-compose.yml down     # remove (PGDATA persists)
```

Connect an Odoo container to the database (DB host = container name, port 5432):

```bash
docker network connect {name}-net <odoo-container>
```

## Troubleshooting

- **Container does not start after conf update:** check `docker logs <name>`; roll back by copying `postgresql.conf.bak-<timestamp>` back into PGDATA.
- **`SHOW ssl` does not return `on`:** check the logs — usually `server.crt`/`server.key` are missing in PGDATA or permissions are wrong (key must be 0600, owner 999:999).
- **Password not accepted:** `POSTGRES_PASSWORD` only applies on first start (initdb). With existing PGDATA, change the password inside the database.

---

**Maintainer:** Equitania Software GmbH · [info@ownerp.com](mailto:info@ownerp.com) · [https://www.ownerp.com](https://www.ownerp.com)
