# PostgreSQL Local Deploy (pg-local-deploy.sh)

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

## Übersicht

`pg-local-deploy.sh` (v1.2.2) ist ein interaktives On-Premise-Deploy-Skript für PostgreSQL-Docker-Container. Es spiegelt das Ansible-Playbook `semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml` auf der lokalen Maschine, damit PostgreSQL-Instanzen auch ohne Semaphore/Ansible-Setup (z.B. Kunden-On-Premise) ausgerollt werden können.

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
| PostgreSQL-Version | neueste vom Docker Hub | Das Skript zeigt den neuesten Patch-Stand jeder Hauptversion, Enter übernimmt den neuesten (z.B. `18.6` → Image `postgres:18.6`). Ohne Verbindung zum Docker Hub wird die Version von Hand eingegeben ([verfügbare Tags](https://hub.docker.com/_/postgres/tags)). Vor einer neuen Hauptversion prüfen, ob die Odoo-Version sie unterstützt. |
| Conf-Profil | `2cpu8gb` | Hardware-Profil (siehe oben) |
| Host-Port | keiner | Optionales Publish auf `127.0.0.1` |
| SSL | `nein` | Self-Signed-SSL aktivieren (y/N) |
| pgvector | `nein` | pgvector installieren (y/N) → Image `postgres-pgvector:<Version>`, siehe unten |

### Volume-Layout

```
{base}/{name}          → PGDATA (5432:5432, 0700; vor 1.4.0 angelegte Instanzen 999:999)
{base}/{name}-deploy/  → docker-compose.yml + postgresql.conf.src
```

### Fester Benutzer (ab 1.4.0)

Eine **neue** Instanz läuft als Benutzer `postgres` mit UID/GID 5432 (`user:` im
Compose-File), nicht mehr als die 999 des offiziellen Images. Die 999 gehört auf
dem Host meist einem Systemkonto, etwa `systemd-coredump`; `ls -l` zeigte PGDATA
deshalb auf jedem Server unter einem anderen, fremden Namen. Das Skript legt den
Host-Benutzer `postgres:5432` ohne Login an, wie `ups` es für `odoo:8069` tut.
Existiert der Name schon mit einer anderen UID, oder gehört die 5432 schon einem
anderen Konto, bleibt beides unverändert; `ls -l` zeigt dann die Zahl.

Ein Re-Deploy auf ein bestehendes PGDATA behält dessen Besitzer. Bestehende
Instanzen werden nicht umgestellt. Ohne root oder sudo kann das Skript den
Besitzer nicht setzen; der Container läuft dann wie bisher als 999.

`PGDATA` wird ausdrücklich auf `/var/lib/postgresql/data` gesetzt. Ab
`postgres:18` liegt der Standard woanders, und das Image startet nicht, wenn
unter dem alten Pfad ein Verzeichnis eingehängt ist, das es nicht benutzt.

## Self-Signed-SSL (optional)

Bei Aktivierung (`y` bei der SSL-Abfrage):

- An die extrahierte `postgresql.conf.src` wird ein markierter Override-Block angehängt (`ssl = on`); die eingebetteten Ansible-Profile bleiben unverändert.
- Beim Conf-Einspielen wird im Postgres-Container per `openssl` ein Self-Signed-Zertifikat erzeugt: RSA 4096, 10 Jahre gültig, `CN = <Container-Name>`, abgelegt als `server.crt`/`server.key` in PGDATA (PostgreSQL-Standardpfade, Key 0600, Besitzer = Benutzer des Containers).
- Idempotent: Ein vorhandenes Zertifikat wird bei Re-Runs nicht überschrieben.
- Die Verifikation prüft `SHOW ssl;` = `on`.

**Hinweise:**

- Odoo-Container mit `db_sslmode = prefer` verschlüsseln die Verbindung automatisch, sobald der Server SSL anbietet — keine Odoo-Änderung nötig.
- Das Zertifikat ist self-signed: Client-Modi mit Zertifikatsprüfung (`verify-ca`/`verify-full`) funktionieren damit nicht.
- Zertifikat manuell erneuern: `server.crt`/`server.key` in PGDATA löschen und das Deploy-Skript erneut ausführen.

## pgvector (optional, ab 1.3.0)

Standard ist **aus**, und das mit Absicht. Odoo 19 Enterprise bringt das Modul
`ai_auto_install` mit: Es wird bei jeder Datenbank automatisch installiert,
prüft, ob der Datenbankserver die Erweiterung `vector` (pgvector) anbietet, und
installiert dann ohne Rückfrage das KI-Modul `ai`. Das Modul kann Texte an
einen externen KI-Anbieter senden. Ohne pgvector passiert nichts davon.

Bei `y` auf „pgvector installieren?“:

- Es wird kein fremdes Image verwendet. Das Skript baut auf `postgres:<Version>`
  das Image `postgres-pgvector:<Version>` und installiert darin
  `postgresql-<Hauptversion>-pgvector` aus dem PostgreSQL-Paketarchiv, das im
  offiziellen Image schon eingetragen ist. Die genaue Version (z.B. 16.14)
  bleibt so erhalten. Der Dockerfile liegt unter `{base}/{name}-deploy/pgvector/`,
  das Compose-File baut damit neu, falls das Image fehlt.
- Der Build braucht Internetzugang zu apt.postgresql.org; gesetzte
  Proxy-Variablen werden durchgereicht.
- Die Verifikation prüft, dass `vector` angeboten wird.

Umgekehrt bricht ein Re-Deploy **ohne** pgvector ab, wenn eine vorhandene
Datenbank die Erweiterung schon nutzt — deren KI-Tabellen wären sonst nicht
mehr lesbar. Das Ansible-Playbook `pb_pg_docker_start.yaml` macht dasselbe mit
`pg_vector=true`; Update und Rollback übernehmen die Einstellung vom laufenden
Server.

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
- **`SHOW ssl` liefert nicht `on`:** Logs prüfen — meist fehlen `server.crt`/`server.key` in PGDATA oder die Rechte stimmen nicht (Key muss 0600 sein und dem Benutzer des Containers gehören, 5432 bzw. bei Altinstanzen 999).
- **Passwort greift nicht:** `POSTGRES_PASSWORD` wirkt nur beim ersten Start (initdb). Bei bestehendem PGDATA das Passwort in der Datenbank ändern.
- **Log füllt sich alle 10 s mit `FATAL: database "<db-user>" does not exist`, Container ist trotzdem `healthy`:** Healthcheck von Containern, die mit < 1.2.2 deployt wurden. Dort fehlte `-d`, also nahm libpq den Benutzernamen als Datenbanknamen; `PQping` wertet die FATAL-Antwort als „Server nimmt Verbindungen an“, der Check blieb grün. Behebung: im Compose-File `pg_isready -U <user>` → `pg_isready -U <user> -d postgres`, dann `docker compose -f … up -d`. Der Healthcheck ist bei der Container-Erstellung eingefroren und lässt sich nicht per `docker container update` ändern — der Container muss neu erzeugt werden (PGDATA bleibt). Ein erneuter Skript-Lauf schreibt das Compose-File selbst neu.

---

<a id="english-version"></a>
# English Version

## Overview

`pg-local-deploy.sh` (v1.2.2) is an interactive on-premise deploy script for PostgreSQL Docker containers. It mirrors the Ansible playbook `semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml` on the local machine so PostgreSQL instances can be rolled out without a Semaphore/Ansible setup (e.g. customer on-premise).

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
| PostgreSQL version | newest on Docker Hub | The script shows the newest patch release of every major version; Enter takes the newest (e.g. `18.6` → image `postgres:18.6`). Without a connection to Docker Hub the version is typed by hand ([available tags](https://hub.docker.com/_/postgres/tags)). Before choosing a new major version, check that the Odoo version supports it. |
| Conf profile | `2cpu8gb` | Hardware profile (see above) |
| Host port | none | Optional publish on `127.0.0.1` |
| SSL | `no` | Enable self-signed SSL (y/N) |
| pgvector | `no` | Install pgvector (y/N) → image `postgres-pgvector:<version>`, see below |

### Volume Layout

```
{base}/{name}          → PGDATA (5432:5432, 0700; instances created before 1.4.0: 999:999)
{base}/{name}-deploy/  → docker-compose.yml + postgresql.conf.src
```

### Fixed User (since 1.4.0)

A **new** instance runs as user `postgres` with UID/GID 5432 (`user:` in the
compose file) instead of the official image's 999. On the host, 999 usually
belongs to a system account such as `systemd-coredump`, so `ls -l` showed PGDATA
under a different, unrelated name on every server. The script creates the host
user `postgres:5432` without a login, as `ups` does for `odoo:8069`. If the name
already exists with another UID, or 5432 belongs to another account, both are
left alone and `ls -l` shows the number.

A re-deploy onto an existing PGDATA keeps its owner. Existing instances are not
migrated. Without root or sudo the script cannot set the owner; the container
then runs as 999, as before.

`PGDATA` is set explicitly to `/var/lib/postgresql/data`. From `postgres:18` the
default lives elsewhere, and the image refuses to start when a directory it does
not use is mounted at the old path.

## Self-Signed SSL (optional)

When enabled (`y` at the SSL prompt):

- A marked override block (`ssl = on`) is appended to the extracted `postgresql.conf.src`; the embedded Ansible profiles remain untouched.
- During conf installation a self-signed certificate is generated inside the postgres container via `openssl`: RSA 4096, valid 10 years, `CN = <container name>`, stored as `server.crt`/`server.key` in PGDATA (PostgreSQL default paths, key 0600, owned by the container's user).
- Idempotent: an existing certificate is kept on re-runs.
- Verification checks `SHOW ssl;` = `on`.

**Notes:**

- Odoo containers with `db_sslmode = prefer` encrypt the connection automatically as soon as the server offers SSL — no Odoo change required.
- The certificate is self-signed: client modes with certificate verification (`verify-ca`/`verify-full`) will not work with it.
- To renew the certificate manually: delete `server.crt`/`server.key` in PGDATA and re-run the deploy script.

## pgvector (optional, since 1.3.0)

The default is **off**, on purpose. Odoo 19 Enterprise ships the module
`ai_auto_install`: it is installed with every database, checks whether the
database server offers the `vector` extension (pgvector) and then installs the
AI module `ai` without asking. That module can send texts to an external AI
provider. Without pgvector none of this happens.

With `y` at "pgvector installieren?":

- No third-party image is used. The script builds `postgres-pgvector:<version>`
  on top of `postgres:<version>` and installs `postgresql-<major>-pgvector` from
  the PostgreSQL package archive the official image already carries. The exact
  version (e.g. 16.14) is kept. The Dockerfile lives in
  `{base}/{name}-deploy/pgvector/`; the compose file rebuilds from it if the
  image is missing.
- The build needs internet access to apt.postgresql.org; proxy variables that
  are set are passed through.
- Verification checks that `vector` is offered.

Conversely, a re-deploy **without** pgvector stops when an existing database
already uses the extension — its AI tables would no longer be readable. The
Ansible playbook `pb_pg_docker_start.yaml` does the same with `pg_vector=true`;
update and rollback inherit the setting from the running server.

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
- **`SHOW ssl` does not return `on`:** check the logs — usually `server.crt`/`server.key` are missing in PGDATA or permissions are wrong (key must be 0600 and owned by the container's user, 5432 or 999 on older instances).
- **Password not accepted:** `POSTGRES_PASSWORD` only applies on first start (initdb). With existing PGDATA, change the password inside the database.
- **Log fills with `FATAL: database "<db-user>" does not exist` every 10 s while the container reports `healthy`:** healthcheck of containers deployed with < 1.2.2. It lacked `-d`, so libpq fell back to the database named after the user; `PQping` treats the FATAL reply as "server accepts connections", so the check stayed green. Fix: in the compose file change `pg_isready -U <user>` → `pg_isready -U <user> -d postgres`, then `docker compose -f … up -d`. The healthcheck is frozen into the container at creation time and cannot be changed via `docker container update` — the container has to be recreated (PGDATA survives). Re-running the script rewrites the compose file by itself.

---

**Maintainer:** Equitania Software GmbH · [info@ownerp.com](mailto:info@ownerp.com) · [https://www.ownerp.com](https://www.ownerp.com)
