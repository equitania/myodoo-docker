# Updates einrichten und fahren / Setting Up and Running Updates

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Updates einrichten und fahren

<a id="de-10-schritt-8-updates-einrichten-edupdoup"></a>
## Schritt 8: Updates einrichten (edup/doup)

`update_docker_odoo.py` aktualisiert die Odoo-Container automatisiert
(Image-Rebuild, Container-Neuanlage, Modul-Update) — gesteuert über
`~/docker2update.yaml`:

```bash
edup    # YAML bearbeiten (mcedit)
doup    # Update-Lauf starten
```

Beispiel-Eintrag pro Container (Vorlage: `scripts/docker2update.yaml`):

```yaml
containers:
  - active: true
    type: "F"                        # [M]odules | [F]ull | [N]eutralize
    delay_time: 10
    container_name: "live-odoo"
    database_name: "live_odoo"
    port: "127.0.0.1:11000"
    longpolling_port: "127.0.0.1:12000"
    dockerfile_path: "$HOME/docker-builds/live-odoo/"
    docker_image_name: "odoo/live"
    db_user: "ownerp"
    db_password: "***"
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "19"
    translate: "Y"
```

Nützliche Optionen: `doup --validate` (Config prüfen), `-s CONTAINER`
(einzelner Container), `-v` (verbose). **Proxy-Kunden:** `defaults.proxy` und
`pre_build_files` in der YAML, Daemon-Proxy via `getScripts.py --proxy-check`.

### Server ohne jede Konfiguration

Fehlen `container2backup.yaml` und `docker2update.yaml` beide — etwa nach
einem CSV-Löschfenster oder auf einem frisch übernommenen Server —, meldet
`ups` das und bietet am Terminal direkt einen Weg heraus: die Konfiguration
aus den laufenden Containern wiederherstellen (`ownerp_migrate.py
--from-docker`), Backup- und Build-Cache-Job bewusst abschalten (für Server,
die wirklich keine Backups und keine Odoo-Updates brauchen, etwa ein
Entwickler-Terminalserver), oder später entscheiden. Läuft `ups` unbeaufsichtigt
— aus einem Skript, per Cron, ohne Terminal —, erscheint nur ein Hinweis und
nichts wird automatisch verändert. Abschalten geschieht über `docron --disable
container2backup` bzw. `docron --disable odoo_build_cache` und lässt die
Zeitpläne stehen; rückgängig mit `docron --enable <job>`.

### Einzelne Systeme, Modus und Kommentar

`doup` fährt alle aktiven Instanzen. Für einen einzelnen Lauf genügen Argumente —
`-s` ist wiederholbar und stärker als `active: false` in der YAML, `--type`
überschreibt den Modus einmalig, `--comment` landet in der Laufhistorie und im
Kopf des Laufprotokolls.

```bash
doup                                 # alle aktiven Instanzen
doup -s live-odoo --type F           # ein System, Modus einmalig
doup -s live-odoo,test-odoo          # mehrere
doup -s live-odoo --comment "eq_stock nachgezogen"
```

> **Die Auswahlmaske `tui` gibt es seit dem 13.08.2026 nicht mehr.** Sie war eine
> Oberfläche für `doup` und beantwortete eine Frage, die Operatoren nicht stellen —
> `doup -s live` tat das immer schon. Welche Instanzen es gibt und wie sie
> konfiguriert sind, zeigt und bearbeitet `konsole`; den Zustand als Text liefert
> `dostat`.

Jeder Lauf landet in `~/update-history.jsonl`: wann, welches System, welcher
Modus, welches Ergebnis, welcher Kommentar.

**Protokoll jedes Laufs.** Unabhängig von `-v` schreibt jeder Lauf eine
vollständige Logdatei in den Build-Ordner der Instanz:
`~/docker-builds/<name>/update_JJJJMMTT_HHMMSS.log`. Sie enthält auch die
INFO-Zeilen, die die Konsole ohne `-v` verschweigt — für die Frage, was der
nächtliche Cron-Lauf getan hat, ist genau das der interessante Teil. Die Pfade
werden am Ende genannt, auch wenn der Lauf abgebrochen ist oder gescheitert.
Dank `.dockerignore` liegen sie außerhalb des Build-Kontexts und kosten keine
Build-Zeit.

Aufgeräumt wird beim jeweils nächsten Lauf derselben Instanz: Standard sind
**90 Tage**, einstellbar über `defaults.log_retention_days` in der YAML oder
`log_retention_days` am einzelnen Container; `0` behält alles. Gelöscht werden
ausschließlich Dateien, deren Name exakt dem Muster `update_JJJJMMTT_HHMMSS.log`
folgt — eine eigene `build.log` im selben Ordner bleibt unangetastet, und
Unterordner wie `filestore-backup/` werden nicht durchsucht. Das Alter stammt
aus dem Dateinamen, nicht aus der mtime: der Name sagt, wann der Lauf war, die
mtime nur, wann die Datei zuletzt angefasst wurde.

**Build-Cache.** Vor jedem Build lädt `odoo_build_cache.py` die Release-Archive
auf den Host nach `/opt/odoo-build-cache` und verlinkt sie in den Build-Ordner
— alle Instanzen desselben Release teilen sich denselben Bestand, gebaut wird
nur noch mit dem, was sich geändert hat. Der Cache blockiert nie einen Build:
was er nicht liefert, lädt `build_odoo.py` wie zuvor selbst. Aufräumen erledigt
der Wartungs-Cron (`gc`, 30 Tage), `~/odoo_build_cache.py stats` zeigt die
Belegung pro Release.

Derselbe Schritt hält die **Dockerfile des Build-Ordners** aktuell. Diese Datei
gehört dem Kunden — `doup` überschreibt sie nie, weil sie eigene `COPY`- und
`RUN`-Schritte tragen kann. Deshalb kam etwa der `HEALTHCHECK` vom März 2026 nie
auf älteren Installationen an. Fehlende Image-Direktiven (`HEALTHCHECK`,
`VOLUME`, `EXPOSE`) werden jetzt ergänzt, vorher wird eine `.bak_<Zeitstempel>`
geschrieben. Zusätzlich wird ein `ADD` an das `COPY` der Repository-Vorlage
angeglichen, sofern beides nachweislich dasselbe tut (einfacher lokaler Pfad —
niemals bei URL, Archiv oder Platzhalter, weil `ADD` dort lädt bzw. entpackt).
Alles, was darüber hinaus nur *abweicht*, erscheint als Warnung mit der exakten
Zeile im Abschlussblock von `doup` und bleibt Handarbeit.

Genauso wird die **`odoo.conf` des Build-Ordners** gepflegt, die aus demselben
Grund nie verteilt wird: sie enthält `admin_passwd` und `db_password`. Ergänzt
werden ausschließlich zentral verwaltete Schlüssel und nur dort, wo der Kunde
keinen eigenen Wert gesetzt hat — ein leerer Wert zählt dabei als nicht gesetzt,
weil Odoo ihn selbst so behandelt. Erster Schlüssel ist `http_interface`: Odoo 19
warnt, wenn er fehlt, und **Odoo 20 stellt den Vorgabewert auf `127.0.0.1` um**,
womit jeder Container über seinen veröffentlichten Port unerreichbar wäre. Auch
hier wird vorher eine `.bak_<Zeitstempel>` geschrieben, und der Schreibvorgang
wird verweigert, sobald sich sonst irgendeine Einstellung ändern würde.

<a id="de-odoo-uid-8069"></a>
### Besitzer der Odoo-Daten: UID/GID 8069

Seit 07.10.2026 legen die Images den Benutzer `odoo` mit der festen **UID/GID
8069** an. Vorher bekam er die erste freie UID des Basis-Images, meist 1000. Auf
dem Host gehört diese Nummer dem Standardbenutzer des Cloud-Images (`debian`,
`ubuntu`) oder einem Admin-Konto, deshalb zeigte `ls -l` auf den Datenordnern je
nach Server einen anderen, fremden Namen. Das Dateisystem speichert nur die
Nummer, den Namen löst `ls` über die `/etc/passwd` **des Hosts** auf.

**Umstellung pro Server, einmalig:** zuerst `ups`, dann `doup`.

1. `ups` (getScripts ≥ 9.29.0) legt als root den Host-Benutzer `odoo` mit
   UID/GID 8069 an: ohne Home, ohne Login-Shell, gesperrt. Ein vorhandenes
   `odoo` mit anderer UID (etwa von einer nativen Odoo-Installation) oder ein
   anderer Inhaber der 8069 bleibt unangetastet und steht in der
   Install-Zusammenfassung.
2. `doup` (update_docker_odoo ≥ 5.24.0, odoo_build_cache ≥ 1.7.0) ersetzt im
   Dockerfile des Build-Ordners die alte `adduser`-Zeile durch die mit
   `--uid 8069` (mit `.bak_<Zeitstempel>`). Nach dem Build und vor dem ersten
   Start prüft es `/opt/odoo/data` im neuen Image und übergibt die Daten einmal
   per `chown -R` an dessen odoo-Benutzer. In der Ausgabe erscheint das als
   `data owner uid 1000 -> 8069`. Bei großen Filestores dauert das Minuten,
   danach kostet die Prüfung pro Lauf ein kurzes `docker run`.

Prüfen:

```fish
ls -ln /opt/odoo                       # Besitzer der Datenordner als Nummer
docker exec <container> id odoo        # erwartet: uid=8069(odoo) gid=8069(odoo)
getent passwd 8069                     # erwartet: odoo:x:8069:8069:...
```

`docker exec <container> id` ohne `odoo` zeigt immer root: Der Container startet
als root und gibt erst beim Start von Odoo an `odoo` ab (siehe unten).

**Zeigt `ls -l` nach `doup` noch den alten Namen**, zuerst die Skriptversionen
prüfen (`grep -m1 SCRIPT_VERSION ~/update_docker_odoo.py ~/odoo_build_cache.py
~/getScripts.py`). Beim ersten Server lag es genau daran, dass `ups` noch nicht
gelaufen war. Liegt danach im Build-Ordner kein neues `Dockerfile.bak_…` und
meldet `doup` „missing a repository instruction … adduser“, weicht die
`adduser`-Zeile des Kunden von der Original-Zeile ab und muss von Hand angepasst
werden.

**Warum nicht `docker run --user`:** Die Images starten bewusst als root. Erst
`bin/boot` setzt die Rechte auf ein leeres Datenverzeichnis und startet Odoo per
`su - odoo`, Odoo selbst läuft also nie als root. Mit `--user` scheitert dieses
`su`, und der Container startet nicht. Die UID gehört deshalb ins Image.

**Eine andere UID wählen** (z. B. wenn ein Kunde eine eigene Benutzerverwaltung
hat): im Dockerfile des Build-Ordners beide Nummern in der `adduser`-Zeile
ändern, den Host-Benutzer anpassen, dann `doup`. Die Rechteanpassung der Daten
folgt automatisch (`data owner uid 8069 -> <neu>`). Eine Zeile mit eigener
`--uid` lässt `odoo_build_cache.py` stehen und meldet sie nicht als Abweichung
(≥ 1.7.1). Die Nummer darf auf dem Host keinem anderen Konto gehören und sollte
nicht unter 1000 liegen. `ups` meldet danach in der Zusammenfassung, dass es den
Host-Benutzer 8069 nicht anlegt, weil `odoo` schon existiert. Das ist gewollt.

```fish
# Host-Benutzer von 8069 auf z. B. 1001 umstellen (als root)
groupmod -g 1001 odoo; usermod -u 1001 -g 1001 odoo
```

---

<a id="english"></a>
# Setting Up and Running Updates

<a id="en-10-step-8-set-up-updates-edupdoup"></a>
## Step 8: Set Up Updates (edup/doup)

`update_docker_odoo.py` updates the Odoo containers automatically (image
rebuild, container re-creation, module update) — driven by
`~/docker2update.yaml`:

```bash
edup    # edit the YAML (mcedit)
doup    # run the update
```

Example entry per container (template: `scripts/docker2update.yaml`):

```yaml
containers:
  - active: true
    type: "F"                        # [M]odules | [F]ull | [N]eutralize
    delay_time: 10
    container_name: "live-odoo"
    database_name: "live_odoo"
    port: "127.0.0.1:11000"
    longpolling_port: "127.0.0.1:12000"
    dockerfile_path: "$HOME/docker-builds/live-odoo/"
    docker_image_name: "odoo/live"
    db_user: "ownerp"
    db_password: "***"
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "19"
    translate: "Y"
```

Useful options: `doup --validate` (check config), `-s CONTAINER` (single
container), `-v` (verbose). **Proxy customers:** `defaults.proxy` and
`pre_build_files` in the YAML, daemon proxy via `getScripts.py --proxy-check`.

### A server with no configuration at all

When both `container2backup.yaml` and `docker2update.yaml` are missing —
after a CSV deletion window, say, or on a freshly taken-over server — `ups`
reports it and, at the terminal, offers a way out directly: rebuild the
configuration from the running containers (`ownerp_migrate.py
--from-docker`), deliberately switch off the backup and build-cache jobs (for
a server that genuinely needs neither backups nor Odoo updates, such as a
developers' terminal server), or decide later. When `ups` runs unattended —
from a script, from cron, with no terminal attached — only a hint is printed
and nothing changes on its own. Switching off goes through `docron --disable
container2backup` and `docron --disable odoo_build_cache` and leaves the
schedules in place; undo with `docron --enable <job>`.

### Single systems, mode and comment

`doup` runs every active instance. A single run needs nothing but arguments:
`-s` is repeatable and stronger than `active: false` in the YAML, `--type`
overrides the mode just this once, and `--comment` lands in the run history and
in the header of the run log.

```bash
doup                                 # every active instance
doup -s live-odoo --type F           # one system, mode just this once
doup -s live-odoo,test-odoo          # several
doup -s live-odoo --comment "pulled in eq_stock"
```

> **The `tui` selection screen was withdrawn on 13.08.2026.** It was a front end
> for `doup` and answered a question operators do not ask — `doup -s live` always
> did that. What instances exist and how they are configured is shown and edited
> by `konsole`; `dostat` gives the same state as text.

Every run is recorded in `~/update-history.jsonl`: when, which system, which
mode, which result, which comment.

**Every run leaves a log.** Regardless of `-v`, each run writes a full log into
the instance's build folder: `~/docker-builds/<name>/update_YYYYMMDD_HHMMSS.log`.
It includes the INFO lines the console withholds without `-v` — which is exactly
the interesting part when the question is what last night's cron run did. The
paths are named at the end, after an abort or a failure too. Thanks to
`.dockerignore` they sit outside the build context and cost no build time.

Cleanup happens on that instance's next run: **90 days** by default, adjustable
via `defaults.log_retention_days` in the YAML or `log_retention_days` on the
individual container; `0` keeps everything. Only files whose name matches
`update_YYYYMMDD_HHMMSS.log` exactly are ever deleted — a `build.log` of your
own in the same folder stays untouched, and subfolders such as
`filestore-backup/` are not searched. The age comes from the file name, not the
mtime: the name says when the run happened, the mtime only says when the file
was last touched.

**Build cache.** Before every build, `odoo_build_cache.py` fetches the release
archives onto the host into `/opt/odoo-build-cache` and links them into the
build folder — every instance on the same release shares one set, and a build
downloads only what actually changed. The cache never blocks a build: whatever
it does not supply, `build_odoo.py` fetches itself as before. The maintenance
cron handles cleanup (`gc`, 30 days); `~/odoo_build_cache.py stats` shows the
size per release.

The same step keeps the **build folder's Dockerfile** current. That file belongs
to the customer — `doup` never overwrites it, because it may carry its own
`COPY` and `RUN` steps. This is why, for instance, the March 2026 `HEALTHCHECK`
never reached older installations. Absent image directives (`HEALTHCHECK`,
`VOLUME`, `EXPOSE`) are now filled in, with a `.bak_<timestamp>` written first.
An `ADD` is additionally aligned with the reference's `COPY` where the two
provably do the same thing (a plain local path — never a URL, an archive or a
wildcard, since `ADD` fetches or unpacks those). Anything that merely *differs*
beyond that is reported with its exact line in the closing block of `doup` and
stays manual.

The **build folder's `odoo.conf`** is maintained the same way and for the same
reason: it is never distributed either, because it holds `admin_passwd` and
`db_password`. Only centrally managed keys are filled in, and only where the
customer set no value of their own — an empty value counts as none, because Odoo
itself treats it that way. The first managed key is `http_interface`: Odoo 19
warns when it is unset, and **Odoo 20 changes the default to `127.0.0.1`**, which
would leave every container unreachable through its published port. A
`.bak_<timestamp>` is written first here too, and the write is refused as soon as
any other setting would change.

<a id="en-odoo-uid-8069"></a>
### Owner of the Odoo data: UID/GID 8069

Since 07.10.2026 the images create the `odoo` user with the fixed **UID/GID
8069**. Before, it got the base image's first free UID, mostly 1000. On the host
that number belongs to the cloud image's default user (`debian`, `ubuntu`) or an
administrator's account, so `ls -l` on the data folders showed a different,
foreign name depending on the server. The file system stores only the number;
`ls` resolves the name through the **host's** `/etc/passwd`.

**Switching a server over, once:** first `ups`, then `doup`.

1. `ups` (getScripts ≥ 9.29.0), run as root, creates the host user `odoo` with
   UID/GID 8069: no home, no login shell, locked. An existing `odoo` with another
   UID (for example from a native Odoo installation) or another owner of 8069 is
   left alone and named in the install summary.
2. `doup` (update_docker_odoo ≥ 5.24.0, odoo_build_cache ≥ 1.7.0) replaces the
   old `adduser` line in the build folder's Dockerfile with the one carrying
   `--uid 8069` (with a `.bak_<timestamp>`). After the build and before the first
   start it checks `/opt/odoo/data` inside the new image and hands the data to
   its odoo user once with `chown -R`. The output shows this as
   `data owner uid 1000 -> 8069`. Large filestores take minutes; afterwards the
   check costs one short `docker run` per run.

Check:

```fish
ls -ln /opt/odoo                       # owner of the data folders as a number
docker exec <container> id odoo        # expected: uid=8069(odoo) gid=8069(odoo)
getent passwd 8069                     # expected: odoo:x:8069:8069:...
```

`docker exec <container> id` without `odoo` always shows root: the container
starts as root and hands over to `odoo` only when it starts Odoo (see below).

**If `ls -l` still shows the old name after `doup`**, check the script versions
first (`grep -m1 SCRIPT_VERSION ~/update_docker_odoo.py ~/odoo_build_cache.py
~/getScripts.py`). On the first server that was exactly the cause: `ups` had not
run yet. If the build folder then has no new `Dockerfile.bak_…` and `doup`
reports "missing a repository instruction … adduser", the customer's `adduser`
line differs from the original line and has to be adjusted by hand.

**Why not `docker run --user`:** the images start as root on purpose. Only
`bin/boot` sets the rights on an empty data directory and starts Odoo through
`su - odoo`, so Odoo itself never runs as root. With `--user` that `su` fails
and the container does not start. The UID therefore belongs in the image.

**Choosing another UID** (for example when a customer has their own user
management): change both numbers in the `adduser` line of the build folder's
Dockerfile, adjust the host user, then `doup`. The data follows automatically
(`data owner uid 8069 -> <new>`). `odoo_build_cache.py` leaves a line with its
own `--uid` in place and does not report it as a deviation (≥ 1.7.1). The number
must not belong to another account on the host and should not be below 1000.
`ups` then reports in its summary that it does not create the host user 8069
because `odoo` already exists. That is intended.

```fish
# Move the host user from 8069 to e.g. 1001 (as root)
groupmod -g 1001 odoo; usermod -u 1001 -g 1001 odoo
```
