# PostgreSQL und Odoo-Container / PostgreSQL and the Odoo Containers

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# PostgreSQL und Odoo-Container

<a id="de-7-schritt-5-postgresql-live-dbtest-db"></a>
## Schritt 5: PostgreSQL (live-db/test-db)

Pro System ein eigener PostgreSQL-Container — interaktiv per:

```bash
~/myodoo-docker/scripts/pg-local-deploy.sh   # Lauf 1: live-db
~/myodoo-docker/scripts/pg-local-deploy.sh   # Lauf 2: test-db
```

Abgefragt werden u.a. Container-Name (`live-db`), Basis-Verzeichnis,
DB-User/-Passwort, PostgreSQL-Version (aktuelle Tags:
<https://hub.docker.com/_/postgres/tags?name=16.>), Performance-Profil
(2cpu4gb … 8cpu32gb) und optional **Self-Signed-SSL**. Das Skript erzeugt
Netzwerk (`live-db-net`), Compose-File (`<basis>/live-db-deploy/docker-compose.yml`)
und startet den Container. Details: [scripts/README_pg-local-deploy.md](../../scripts/README_pg-local-deploy.md).

> ⚠️ **Erfahrungswert (db_sslmode):** In der `odoo.conf` des Odoo-Images muss
> `db_sslmode = prefer` stehen. Mit `require` verweigert Odoo die Verbindung
> zu einem PostgreSQL ohne SSL („server does not support SSL, but SSL was
> required"). Vor dem ersten Start prüfen:
>
> ```fish
> docker run --rm --entrypoint grep odoo/live db_sslmode /opt/odoo/etc/odoo.conf
> # Erwartung: db_sslmode = prefer
> ```

<a id="de-8-schritt-6-odoo-container-erststarten"></a>
## Schritt 6: Odoo-Container erststarten

### 8.1 Image bereitstellen

Entweder aus eurer Registry ziehen oder auf dem Server bauen. Beim Build
liegt pro System ein Build-Verzeichnis vor (z.B. `$HOME/docker-builds/live-odoo/`
mit Dockerfile, `build_odoo.py`, `release.file`, `odoo.conf`, `bin/boot` —
siehe `Dockerfiles/v19-odoo/ReadMe.md`):

```fish
cd $HOME/docker-builds/live-odoo
docker build -t odoo/live .
```

### 8.2 Container starten

```fish
# LIVE
docker run -d -p 127.0.0.1:11000:8069 -p 127.0.0.1:12000:8072 \
  --restart=always --network live-db-net \
  -v /opt/odoo/live:/opt/odoo/data --name="live-odoo" odoo/live:latest start

# TEST
docker run -d -p 127.0.0.1:13000:8069 -p 127.0.0.1:14000:8072 \
  --restart=always --network test-db-net \
  -v /opt/odoo/test:/opt/odoo/data --name="test-odoo" odoo/test:latest start
```

Das Boot-Skript im Container akzeptiert genau drei Kommandos:
`start` (Normalbetrieb), `update` (Modul-Update, genutzt von `doup`),
`neutralize` (DB neutralisieren, z.B. nach Restore auf test).

> **Nur `start` liest die `odoo.conf`.** `update` und `neutralize` starten
> `odoo-bin` bewusst ohne `-c`, damit ein Update nicht den `addons_path`, den
> `db_host` und die Worker-Zahl der Instanz erbt. Eine Änderung an der
> `odoo.conf` wirkt sich deshalb erst auf den laufenden Container aus, nicht auf
> die Log-Ausgabe des `update odoo`-Schritts von `doup`.

### 8.3 Verifizieren

```fish
dps                                                # beide Container "Up"?
curl -sI http://127.0.0.1:11000/web/health         # HTTP/1.1 200 OK
docker logs --tail 20 live-odoo                    # Fehler im Log?
```

Danach im Browser `https://erp-live.example.com` → Datenbank anlegen.
Die `odoo.conf` je Instanz zeigt per `db_host` auf den DB-Container
(`live-db` bzw. `test-db`) — die Namensauflösung übernimmt das Docker-Netz.

> ⚠️ **Erfahrungswerte:**
> - **Immer mit `127.0.0.1:`-Prefix mappen.** Ohne Prefix lauschen 11000/12000
>   auf allen Interfaces — jeder im LAN umgeht dann nginx, SSL und
>   Security-Header.
> - Schlägt der Start mit `exec /app/bin/boot: no such file or directory`
>   fehl, obwohl das Build-Verzeichnis korrekt ist → fast immer der
>   Docker-29-Store-Bug, siehe [Troubleshooting](08-troubleshooting.md#de-16-troubleshooting).

---

<a id="english"></a>
# PostgreSQL and the Odoo Containers

<a id="en-7-step-5-postgresql-live-dbtest-db"></a>
## Step 5: PostgreSQL (live-db/test-db)

One dedicated PostgreSQL container per system — interactively via:

```bash
~/myodoo-docker/scripts/pg-local-deploy.sh   # run 1: live-db
~/myodoo-docker/scripts/pg-local-deploy.sh   # run 2: test-db
```

Prompts include container name (`live-db`), base directory, DB user/password,
PostgreSQL version (current tags:
<https://hub.docker.com/_/postgres/tags?name=16.>), performance profile
(2cpu4gb … 8cpu32gb) and optional **self-signed SSL**. The script creates the
network (`live-db-net`), a compose file
(`<base>/live-db-deploy/docker-compose.yml`) and starts the container.
Details: [scripts/README_pg-local-deploy.md](../../scripts/README_pg-local-deploy.md).

> ⚠️ **Lesson learned (db_sslmode):** The `odoo.conf` inside the Odoo image
> must contain `db_sslmode = prefer`. With `require`, Odoo refuses to talk to
> a PostgreSQL without SSL ("server does not support SSL, but SSL was
> required"). Check before the first start:
>
> ```fish
> docker run --rm --entrypoint grep odoo/live db_sslmode /opt/odoo/etc/odoo.conf
> # expected: db_sslmode = prefer
> ```

<a id="en-8-step-6-first-start-of-the-odoo-containers"></a>
## Step 6: First Start of the Odoo Containers

### 8.1 Provide the image

Either pull from your registry or build on the server. For a build, each
system has a build directory (e.g. `$HOME/docker-builds/live-odoo/` with
Dockerfile, `build_odoo.py`, `release.file`, `odoo.conf`, `bin/boot` — see
`Dockerfiles/v19-odoo/ReadMe.md`):

```fish
cd $HOME/docker-builds/live-odoo
docker build -t odoo/live .
```

### 8.2 Start the containers

```fish
# LIVE
docker run -d -p 127.0.0.1:11000:8069 -p 127.0.0.1:12000:8072 \
  --restart=always --network live-db-net \
  -v /opt/odoo/live:/opt/odoo/data --name="live-odoo" odoo/live:latest start

# TEST
docker run -d -p 127.0.0.1:13000:8069 -p 127.0.0.1:14000:8072 \
  --restart=always --network test-db-net \
  -v /opt/odoo/test:/opt/odoo/data --name="test-odoo" odoo/test:latest start
```

The boot script inside the container accepts exactly three commands:
`start` (normal operation), `update` (module update, used by `doup`),
`neutralize` (neutralize the DB, e.g. after restoring onto test).

> **Only `start` reads `odoo.conf`.** `update` and `neutralize` launch
> `odoo-bin` without `-c` on purpose, so an update cannot inherit the instance's
> `addons_path`, `db_host` and worker count. A change to `odoo.conf` therefore
> takes effect on the running container only — not on the log output of `doup`'s
> `update odoo` step.

### 8.3 Verify

```fish
dps                                                # both containers "Up"?
curl -sI http://127.0.0.1:11000/web/health         # HTTP/1.1 200 OK
docker logs --tail 20 live-odoo                    # errors in the log?
```

Then open `https://erp-live.example.com` in a browser → create the database.
Each instance's `odoo.conf` points at its DB container via `db_host`
(`live-db` / `test-db`) — name resolution is handled by the Docker network.

> ⚠️ **Lessons learned:**
> - **Always map with the `127.0.0.1:` prefix.** Without it, 11000/12000
>   listen on all interfaces — anyone on the LAN bypasses nginx, SSL and the
>   security headers.
> - If the start fails with `exec /app/bin/boot: no such file or directory`
>   although the build directory is correct → almost always the Docker 29
>   store bug, see [Troubleshooting](08-troubleshooting.md#en-16-troubleshooting).
