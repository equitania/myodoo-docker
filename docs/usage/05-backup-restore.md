# Backup und Restore / Backup and Restore

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Backup und Restore

<a id="de-11-schritt-9-backups-einrichten-edbkdobk"></a>
## Schritt 9: Backups einrichten (edbk/dobk)

`container2backup.py` sichert SQL-Dump + Filestore je Datenbank sowie
Service-Verzeichnisse (nginx, letsencrypt, docker-builds) — gesteuert über
`~/container2backup.yaml`:

```bash
edbk    # YAML bearbeiten
dobk    # Voll-Backup ausfuehren
dobk --sql-only
llbk    # Backup-Verzeichnis ansehen (/opt/backups/docker)
```

Beispiel (Vorlage: `scripts/container2backup.yaml`):

```yaml
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression: { format: "7z", level: 5 }
  stream: false          # true = Streaming .tar.zst (grosse Filestores!)

databases:
  - name: live_odoo
    sql_container: live-db
    data_container: live-odoo
  - name: test_odoo
    sql_container: test-db
    data_container: test-odoo
    only_sql_dump: true
```

> 💡 **Erfahrungswert:** Bei großen Filestores (≫ 50 GB) `stream: true`
> setzen — das Backup läuft ohne unkomprimierte Zwischenkopie direkt in ein
> `.tar.zst`. Kompressionslevel 3 genügt (Filestore-Medien sind bereits
> komprimiert). Details, Verschlüsselung (AES-256/GPG) und Restore je Format:
> [scripts/README_BackUp.md](../../scripts/README_BackUp.md).

### Konfiguration prüfen (doval)

Nach jeder manuellen Änderung an `docker2update.yaml` oder
`container2backup.yaml` lohnt sich ein kurzer Check, bevor der nächste `doup`
oder `dobk` darauf läuft:

```bash
doval                # beide Konfigurationen an ihren Standardpfaden prüfen
doval --update       # nur docker2update.yaml
doval --backup       # nur container2backup.yaml
```

`ownerp_validate.py` ist **rein lesend** — es schreibt nie in die YAML — und
prüft Pflichtfelder, Typen, Portform, doppelte Container-/Datenbanknamen und
-Ports (nur unter aktiven Einträgen) sowie unbekannte Schlüssel. Jeder Befund
nennt Datei und Zeilennummer.

**Die drei Exitcodes:**

| Exitcode | Bedeutung |
|---|---|
| `0` | keine Fehler. **Warnungen können trotzdem ausgegeben worden sein** — sie zählen für den Exitcode nicht |
| `1` | mindestens ein Fehler |
| `2` | eine Datei fehlt, ist unlesbar, nicht parsebar, oder PyYAML ist nicht installiert |

Ein Cronjob oder Wrapper-Skript, das auf `doval` aufsetzt, muss also den
Exitcode prüfen (`$status` in fish) — nicht, ob überhaupt etwas ausgegeben
wurde, denn Warnungen erscheinen auch bei Exitcode `0`.

### Eine Instanz aufnehmen, geführt (wiz)

Eine weitere Odoo-Instanz von Hand in `docker2update.yaml` einzutragen heißt:
einen bestehenden Block kopieren und zwölf Werte ändern, darunter zwei
Host-Ports, die mit nichts kollidieren dürfen. `wiz` führt stattdessen durch
die Felder:

```bash
wiz                                  # Menü: 1) Instanz aufnehmen  2) Feld ändern
python3 ~/ownerp_wizard.py --update ~/docker2update.yaml
```

Der Assistent liest die Konfiguration, **bevor** er etwas fragt, und schlägt
aus ihr vor — den nächsten freien Host-Port, den Build-Ordner nach dem Muster
der vorhandenen Einträge, den Image-Namen nach deren Konvention. Der Vorschlag
steht in eckigen Klammern und wird mit Enter übernommen; wo die Einträge sich
uneinig sind, schlägt er nichts vor, statt zu raten. Das Passwort wird nicht
angezeigt und erscheint in der Zusammenfassung als `********`.

**Geschrieben wird erst, wenn das Ergebnis die Prüfung besteht.** Der Ablauf
ist immer derselbe:

1. Sicherung nach `~/docker2update.yaml.bak-<JJJJMMTT_HHMMSS>`
2. der neue Text landet in einer temporären Datei **im selben Verzeichnis**
3. `ownerp_validate.py` prüft genau diese Datei
4. **Fehler** → temporäre Datei *und* Sicherung werden entfernt, das Original
   bleibt Byte für Byte unverändert, und der Assistent bietet an, das
   beanstandete Feld zu korrigieren
5. **sauber** → die Datei wird atomar ersetzt, die Sicherung bleibt liegen

Eine Sicherung bleibt also nur dann zurück, wenn tatsächlich etwas geändert
wurde — findet sich nach einem Lauf keine `.bak-*`-Datei, wurde die
Konfiguration nicht angefasst. Warnungen blockieren nicht: ein noch nicht
existierender Build-Ordner ist bei einer neuen Instanz der Normalfall, und der
Assistent bietet an, ihn leer anzulegen (mehr nicht — befüllt wird er beim
ersten `doup`).

> **Was `wiz` bewusst nicht tut:** Er **entfernt nie einen Eintrag**, und er
> bearbeitet nur einzelne Werte. Listen und Unterblöcke (`pre_build_files`,
> `proxy`) zeigt er an, ändert sie aber nicht — dafür bleibt `edup` (mcedit)
> zuständig. Ohne Terminal verweigert er den Start, ist also für Cronjobs
> ungeeignet und dort auch nicht nötig.

In der Konsole `konsole` bearbeitet `[e]` denselben Eintrag als Formular; danach
lädt die Maske die Liste neu, damit die neue Instanz sofort auswählbar ist.

<a id="de-13-restore--notfall"></a>
## Restore & Notfall

Backup zurückspielen (Archiv aus `container2backup.py`, erkennt
`.zip/.7z/.7z.gpg/.tar.gz/.tar.zst` automatisch):

```bash
env PGPASSWORD='<pg_password>' ~/myodoo-docker/scripts/restore-zip.sh \
  <backup_kind 1|2> <run_sql> <orig_dbname> <new_dbname> <drop_db Y/n> \
  <archiv> <odoo_volume> <pg_container>
```

Das Passwort per `PGPASSWORD`-Umgebungsvariable übergeben — als 9. Argument
wäre es in `ps aux` und der Shell-History sichtbar (das Skript warnt dann).

Typischer Anwendungsfall: Live-Backup als Test-DB einspielen, danach im
Container `neutralize` ausführen (Mails/Cron deaktivieren). Für manuelle
Container-Updates ohne `doup` (Fallback):
[docs/MANUAL_DOCKER_UPDATE_GUIDE.md](../MANUAL_DOCKER_UPDATE_GUIDE.md).

---

<a id="english"></a>
# Backup and Restore

<a id="en-11-step-9-set-up-backups-edbkdobk"></a>
## Step 9: Set Up Backups (edbk/dobk)

`container2backup.py` backs up the SQL dump + filestore per database plus
service directories (nginx, letsencrypt, docker-builds) — driven by
`~/container2backup.yaml`:

```bash
edbk    # edit the YAML
dobk    # run a full backup
dobk --sql-only
llbk    # list the backup directory (/opt/backups/docker)
```

Example (template: `scripts/container2backup.yaml`):

```yaml
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression: { format: "7z", level: 5 }
  stream: false          # true = streaming .tar.zst (large filestores!)

databases:
  - name: live_odoo
    sql_container: live-db
    data_container: live-odoo
  - name: test_odoo
    sql_container: test-db
    data_container: test-odoo
    only_sql_dump: true
```

> 💡 **Lesson learned:** For large filestores (≫ 50 GB) set `stream: true` —
> the backup is piped straight into a `.tar.zst` without an uncompressed
> staging copy. Compression level 3 is enough (filestore media is already
> compressed). Details, encryption (AES-256/GPG) and per-format restore:
> [scripts/README_BackUp.md](../../scripts/README_BackUp.md).

### Validate the configuration (doval)

After any manual edit to `docker2update.yaml` or `container2backup.yaml`, a
quick check before the next `doup` or `dobk` run is worth it:

```bash
doval                # validate both configurations at their default paths
doval --update       # only docker2update.yaml
doval --backup       # only container2backup.yaml
```

`ownerp_validate.py` is **read-only** — it never writes to the YAML — and
checks required fields, types, port form, duplicate container/database names
and ports (among active entries only), and unknown keys. Every finding names
the file and the line number.

**The three exit codes:**

| Exit code | Meaning |
|---|---|
| `0` | no errors. **Warnings may still have been printed** — they do not count against the exit code |
| `1` | at least one error |
| `2` | a file is missing, unreadable, unparseable, or PyYAML is not installed |

A cron job or wrapper script built on top of `doval` must therefore check the
exit code (`$status` in fish) — not whether anything was printed at all,
since warnings appear on exit code `0` too.

### Add an instance, guided (wiz)

Adding another Odoo instance to `docker2update.yaml` by hand means copying an
existing block and changing twelve values, two of them host ports that must
not collide with anything already in the file. `wiz` walks the fields instead:

```bash
wiz                                  # menu: 1) add an instance  2) change a field
python3 ~/ownerp_wizard.py --update ~/docker2update.yaml
```

The assistant reads the configuration **before** it asks anything and proposes
values from it — the next free host port, the build folder following the
pattern of the existing entries, the image name following their convention. A
suggestion sits in square brackets and is taken with Enter; where the entries
disagree, it proposes nothing rather than guessing. The password is not echoed
and appears in the summary as `********`.

**Nothing is written until the result passes validation.** The sequence is
always the same:

1. a backup to `~/docker2update.yaml.bak-<YYYYMMDD_HHMMSS>`
2. the new text goes to a temporary file **in the same directory**
3. `ownerp_validate.py` runs against exactly that file
4. **error** → the temporary file *and* the backup are removed, the original
   is left byte for byte as it was, and the assistant offers to correct the
   field that was rejected
5. **clean** → the file is replaced atomically and the backup stays

A backup is therefore left behind only when something actually changed — no
`.bak-*` file after a run means the configuration was not touched. Warnings do
not block: a build folder that does not exist yet is the normal state for a new
instance, and the assistant offers to create it empty (nothing more — it is
populated by the first `doup`).

> **What `wiz` deliberately does not do:** it **never removes an entry**, and
> it edits single values only. Lists and sub-blocks (`pre_build_files`,
> `proxy`) are shown but not changed — those stay with `edup` (mcedit). It
> refuses to start without a terminal, so it is unsuitable for cron jobs, and
> unnecessary there.

In the console `konsole`, `[e]` edits the same entry as a form; the
screen reloads the list afterwards, so the new instance can be selected right
away.

<a id="en-13-restore--emergency"></a>
## Restore & Emergency

Restore a backup (archive produced by `container2backup.py`; detects
`.zip/.7z/.7z.gpg/.tar.gz/.tar.zst` automatically):

```bash
env PGPASSWORD='<pg_password>' ~/myodoo-docker/scripts/restore-zip.sh \
  <backup_kind 1|2> <run_sql> <orig_dbname> <new_dbname> <drop_db Y/n> \
  <archive> <odoo_volume> <pg_container>
```

Pass the password via the `PGPASSWORD` environment variable — as the 9th
positional argument it would be visible in `ps aux` and shell history (the
script warns in that case).

Typical use case: restore the live backup as the test DB, then run
`neutralize` in the container (disables mails/cron). For manual container
updates without `doup` (fallback):
[docs/MANUAL_DOCKER_UPDATE_GUIDE.md](../MANUAL_DOCKER_UPDATE_GUIDE.md).
