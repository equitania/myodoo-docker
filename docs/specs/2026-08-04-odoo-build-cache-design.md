# Design: Zip-Cache für Odoo-Image-Builds

**Datum:** 04.08.2026
**Betrifft:** `Dockerfiles/v16-odoo/`, `v18-odoo/`, `v19-odoo/`, `scripts/update_docker_odoo.py`
**Status:** Entwurf zur Freigabe

## Ausgangslage

Jeder Image-Build lädt sämtliche Release-Archive neu. Der Ablauf heute:

1. `check_dockerimage_odoo.py` holt mit dem Accesscode aus `release.txt` die `release.file`
   (CSV) vom Release-Manager und patcht die `FROM`-Zeile des Dockerfiles.
2. `update_docker_odoo.py` startet `docker build`.
3. `build_odoo.py` läuft **im Container**, liest die `release.file`, lädt Kernel und jedes
   Modul-Archiv einzeln von der Basis-URL (Zeile 1 der CSV), entpackt sie nach
   `odoo-server/` bzw. `odoo-server/addons/` und löscht am Ende alle `*.zip`.

Nichts davon überlebt den Build. Ein Update, bei dem sich fünf von dreihundert Modulen
geändert haben, lädt dreihundert Archive.

### Warum der vorhandene Docker-Cache nicht trägt

Der `RUN python3 build_odoo.py`-Layer ist Layer-gecacht, aber:

- `update_docker_odoo.py:964` fährt nach jedem Lauf `docker system prune -f`, was den
  Build-Cache entfernt. Derselbe Einwand trifft jede BuildKit-Lösung
  (`RUN --mount=type=cache`).
- Der Layer-Cache ist alles-oder-nichts: eine geänderte Zeile in der `release.file`
  entwertet den gesamten Download-Schritt.

### Der Umstand, der alles vereinfacht

Die Archivnamen tragen die Version. Schematisch (der konkrete Aufbau der Release-URLs
gehört nicht in dieses Dokument):

```
<basis-url>                              <- Zeile 1
<image-referenz>                         <- Zeile 2, hier ohne Bedeutung
<kernel>-<odoo-version>-<datum>.zip      <- Zeile 3: Kernel
<modul>_<odoo-version>.<modul-version>.zip   <- ab Zeile 4: Module
```

Eine neue Modulversion ist eine **neue Datei**, kein neuer Inhalt unter altem Namen.
Damit ist der Dateiname ein gültiger Cache-Schlüssel: liegt er vor, ist der Inhalt
korrekt. Kein ETag, kein `If-Modified-Since`, kein Revalidierungs-Roundtrip.

## Nicht-Ziele

- Kein Ersatz für den Docker-Layer-Cache; beide dürfen nebeneinander wirken.
- Keine Änderung am Release-Manager oder am CSV-Format.
- Keine Beschleunigung des Erstbuilds oder eines vollständig neuen Releases — dort ist
  jede Datei zwangsläufig neu.

## Leitprinzip

**Der Cache ist eine Beschleunigung, keine neue Fehlerquelle.** Jede Stufe fällt auf das
heutige Verhalten zurück:

- Fehlt das Cache-Verzeichnis, lädt `build_odoo.py` wie bisher selbst.
- Schafft der Sync nur einen Teil der Dateien, lädt `build_odoo.py` den Rest.
- Die bestehende Vollständigkeitsprüfung (`failed_modules` → Exit 1) bleibt die
  Autorität darüber, ob ein Image vollständig ist.

Ein defekter oder leerer Cache darf also nie einen Build verhindern.

## Cache-Layout

Serverweit, außerhalb jedes Build-Ordners und außerhalb von Docker:

```
/opt/odoo-build-cache/
  <release-host>/<pfad-der-basis-url>/<kernel-archiv>.zip
  <release-host>/<pfad-der-basis-url>/<modul-archiv>.zip
```

Der Pfad wird aus Host und Pfad der Basis-URL abgeleitet. Damit gilt:

- Zwei Instanzen derselben Version teilen sich jede Datei — sie wird einmal geladen.
- Zwei Odoo-Versionen kollidieren nicht, auch wenn ein Archiv gleich hieße.
- Der Cache liegt nicht unter `$HOME/docker-builds` und wandert damit nicht in das
  Backup (`container2backup.yaml` sichert `$HOME/docker-builds`).

**Kein Index, kein Zustandsfile.** „Zuletzt benutzt“ ist die `mtime` der Datei: bei jedem
Treffer wird sie via `os.utime()` auf jetzt gesetzt. Das macht die Bereinigung zu einem
`find -mtime +30` und vermeidet Sperr- und Konsistenzfragen bei parallelen Läufen.

## Komponenten

### 1. `scripts/odoo_build_cache.py` (neu)

Eigenständiges CLI, damit der Cache prüfbar und aufräumbar ist, ohne einen Build zu
starten. `update_docker_odoo.py` ruft nur `sync` auf.

| Kommando | Wirkung |
|----------|---------|
| `sync <build-dir>` | `release.file` lesen, fehlende Archive laden, Build-Ordner bestücken |
| `gc [--days 30]` | Archive löschen, deren `mtime` älter ist; zusätzlich alte `release.file-*` |
| `stats` | Größe, Dateizahl, Verteilung nach Version — für `server-readiness.py` und manuelle Kontrolle |

`sync` im Detail:

1. `release.file` im Build-Ordner parsen: Basis-URL aus Zeile 1, Archive ab Zeile 3.
   Zeile 2 (Docker-Image) wird übersprungen.
2. Jeden Namen gegen `_SAFE_FILENAME_PATTERN` prüfen — dieselbe Regel wie in
   `build_odoo.py`, gegen Path-Traversal über eine manipulierte CSV.
3. Fehlende Archive laden: Download nach `<name>.tmp`, dann `os.replace()`. Atomar, damit
   ein Abbruch kein halbes Archiv im Cache hinterlässt.
4. **Integritätsprüfung vor der Aufnahme:** `zipfile.is_zipfile()`. Ein Release-Server, der
   im Fehlerfall eine HTML-Seite mit Status 200 liefert, würde den Cache sonst dauerhaft
   vergiften — und anders als heute überlebt der Müll den Build.
5. `<build-dir>/zips/` leeren und neu bestücken: `os.link()` je Archiv, bei `OSError`
   (anderes Dateisystem) `shutil.copy2()`. Das Verzeichnis wird **immer** angelegt, auch
   wenn es leer bleibt.
6. Treffer bekommen ein `os.utime()`.

Retry-Verhalten, Backoff und Circuit Breaker werden aus `build_odoo.py` übernommen
(`BUILD_ODOO_RETRIES`, `BUILD_ODOO_RETRY_BACKOFF`, `BUILD_ODOO_FAILURE_LIMIT`), inklusive
Proxy-Behandlung über `_create_http_pool()`. Ein Fehlschlag beendet `sync` mit einer
Meldung, aber ohne den Build zu blockieren — siehe Leitprinzip.

### 2. `build_odoo.py` (alle drei Versionen, heute byte-identisch)

Eine Änderung: vor dem Download prüfen, ob `zips/<name>` existiert. Wenn ja, direkt von
dort entpacken; wenn nein, herunterladen wie bisher. Der Zähler unterscheidet beide Fälle,
damit die Build-Ausgabe zeigt, wie viel der Cache getragen hat:

```
kernel: <kernel-archiv>.zip (cached)
file: <modul-archiv>.zip (downloaded)
...
295 aus Cache, 5 geladen, 300 gesamt
```

Die Cleanup-Liste am Ende wird um `zips` erweitert, damit die Archive nicht im Image
landen.

### 3. Dockerfile (alle drei Versionen)

Eine Zeile vor dem `RUN`:

```dockerfile
COPY zips/ /opt/odoo/zips/
```

`COPY` scheitert an einer fehlenden Quelle, deshalb legt `sync` das Verzeichnis
bedingungslos an.

**Rollout-Problem:** `sync_build_scripts()` (`update_docker_odoo.py:832`) verteilt nur
`build_odoo.py`, `check_dockerimage_odoo.py` und `bin/` — **nicht** das Dockerfile. Auf
Bestandsservern bliebe die `COPY`-Zeile also aus, und der Cache wirkungslos, ohne dass es
jemand bemerkt. Deshalb fügt `sync` die Zeile idempotent selbst ein, falls sie fehlt, mit
einer Log-Zeile. Das folgt dem im Projekt etablierten Muster: `check_dockerimage_odoo.py`
patcht bereits Zeile 1 und 4 des Dockerfiles per `sed`.

### 4. `.dockerignore` je Version (neu)

Heute existiert keins. Der Build-Context umfasst damit alles im Build-Ordner — und bei
Instanzen ohne Volume liegen dort **zwei** vollständige Filestore-Kopien:
`update_docker_odoo.py:1089` sichert den Filestore per `docker cp` nach `<build-dir>/<db>`,
und Zeile 1338–1349 rotiert ihn nach dem Build zu `<db>.bak`, wobei die vorherige `.bak`
gelöscht wird. Beide gehen heute vollständig an den Docker-Daemon. Dazu die nie
gelöschten `release.file-*`-Archive. Bei einem großen Filestore sind das Gigabytes pro
Build, und die zusätzlichen `zips/` würden es verschlimmern.

```
filestore-backup/
release.file-*
__pycache__/
*.log
```

Der Filestore-Ordner heißt wie die Datenbank und ist damit nicht statisch benennbar.
Deshalb legt `update_docker_odoo.py` ihn künftig unter `filestore-backup/<db_name>` ab
statt im Ordner-Root, und dieser feste Name steht im `.dockerignore`. **Diese Verschiebung
ändert einen bestehenden Ablauf und ist der einzige Punkt des Entwurfs, der nicht rein
additiv ist.** Anzupassen sind beide Stellen: das `docker cp`-Ziel und die
`.bak`-Rotation. Eine Wiederherstellung gibt es nicht — die Kopie ist ein reines
Sicherheitsnetz, weil der Filestore bei diesen Instanzen im Container liegt und der Build
den Container ersetzt.

### 5. Bereinigung

- `odoo_build_cache.py gc --days 30`: Archive ohne Nutzung seit 30 Tagen. Bewusst nicht
  „steht nicht in der aktuellen `release.file`“ — eine andere Instanz kann auf einem
  älteren Release stehen und dieselbe Datei noch brauchen.
- Alte `release.file-<timestamp>` in jedem Build-Ordner: die letzten fünf behalten.
- Aufruf wöchentlich über `myodoo-maintenance.cron`, analog zu den bestehenden Einträgen.

## Fehlerbehandlung

| Fall | Verhalten |
|------|-----------|
| Cache-Verzeichnis fehlt/nicht beschreibbar | Warnung, `sync` endet ohne Fehler, Build lädt wie bisher |
| Einzelner Download scheitert | Datei fehlt in `zips/`, `build_odoo.py` lädt sie im Build |
| Release-Server komplett weg | Circuit Breaker greift, `sync` endet, Build läuft und scheitert mit der bestehenden Meldung |
| Beschädigtes Archiv | `is_zipfile()` verwirft es vor der Aufnahme; nächster Lauf versucht es erneut |
| Platte voll | `sync` meldet den Fehler, Build lädt wie bisher |

## Verifikation

- `sync` gegen ein Fixture-Verzeichnis mit einer synthetischen `release.file` und einem
  lokalen HTTP-Server: erster Lauf lädt alles, zweiter Lauf lädt nichts.
- Ein Archiv im Cache gegen eine HTML-Seite tauschen → muss verworfen und neu geladen
  werden.
- `gc --days 0` gegen ein Fixture: löscht alles, lässt die letzten fünf `release.file-*`
  stehen.
- Dockerfile-Patch zweimal ausführen → beim zweiten Mal keine Änderung.
- Ein echter Build je Version, mit gezähltem Cache-Anteil in der Ausgabe.

## Rollout

1. `odoo_build_cache.py` in `copy_scripts()` von `getScripts.py` aufnehmen, damit `ups` es
   verteilt.
2. `build_odoo.py`, Dockerfile und `.dockerignore` in allen drei Versionsordnern
   angleichen — die drei `build_odoo.py` sind heute byte-identisch (`4b98ac28…`) und
   sollen es bleiben.
3. Erster `doup`-Lauf füllt den Cache vollständig (kein Gewinn), ab dem zweiten greift er.

## Offene Punkte

- Ob `/opt/odoo-build-cache` auf demselben Dateisystem wie `$HOME/docker-builds` liegt,
  entscheidet über Hardlink oder Kopie. Der Code behandelt beides, aber bei getrennten
  Dateisystemen verdoppelt sich der Platzbedarf während des Builds.
- Die Größe des Build-Contexts nach der Umstellung ist zu messen: die `zips/` wandern
  künftig durch den Context, was lokal ein Kopiervorgang statt hunderter HTTPS-Downloads
  ist — der Gewinn sollte deutlich sein, ist aber unbelegt, solange es keine Zahl gibt.
