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
