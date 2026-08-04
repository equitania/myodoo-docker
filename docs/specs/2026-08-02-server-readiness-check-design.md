# Server Readiness Check — Design

**Datum:** 02.08.2026
**Status:** Entwurf, zur Freigabe
**Betrifft:** `scripts/server-readiness.py` (neu), `getScripts.py`, `scripts/myodoo-maintenance.cron`, `fish/functions/linux/`

## Problem

`getScripts.py` liefert über `copy_scripts()` (Zeile 3668) alle Wartungswerkzeuge nach `/root` aus —
darunter `setup-maintenance-cron.sh`, `myodoo-maintenance.cron` und `myodoo-maintenance.logrotate`.
Ausgeführt oder auch nur erwähnt wird davon nichts. Das Repository weiß also genau, welcher Zustand
auf einem Server herrschen sollte, teilt dem Administrator aber nie mit, ob er tatsächlich herrscht.

Konkreter Schaden im Feld: Auf Servern mit handgepflegtem `crontab -e`-Eintrag für
`container2backup.py` wurde `setup-maintenance-cron.sh` nie ausgeführt. Damit fehlt
`/etc/logrotate.d/myodoo-maintenance`, und `/var/log/container2backup.log` wächst seit
Inbetriebnahme unbegrenzt. Erkennbar war das bisher nur durch gezieltes Nachsehen.

Der Administrator muss den Soll-Zustand im Kopf haben und Stück für Stück manuell abprüfen.

## Ziel

Ein Kommando beantwortet die Frage „Ist dieser Server auf dem aktuellen Stand, und was fehlt noch?“
mit einer Ampel-Liste. Zu jedem Befund gehört genau ein kopierfertiger Befehl zur Behebung.

## Nicht-Ziele

Bewusst ausgeschlossen, um den Umfang klein zu halten:

- **Kein Auto-Fix.** Der Check ist ausschließlich lesend. Er schreibt nichts nach `/etc`.
- **Keine Netzwerkzugriffe.** Alle Prüfungen laufen lokal, damit der Report in Sekunden fertig ist
  und auch auf Proxy-Hosts ohne Weiteres funktioniert.
- **Keine Historie, keine Statusdatei, keine JSON-Ausgabe.** Kann später folgen, wenn sich ein
  konkreter Bedarf zeigt.
- **Keine Remote-Prüfung** anderer Hosts.
- **`scripts/lib/` wird nicht angefasst.** Siehe „Nebenbefund“ am Ende.

## Struktur

Eigenständiges Skript `scripts/server-readiness.py`, ausgeliefert über die Liste in `copy_scripts()`.

Damit folgt es dem Muster der übrigen Wartungswerkzeuge (`nginx-cert-guard.py`,
`cleanup-weblogs.py`, `nightly-cleanup.sh`) und gewinnt zwei Eigenschaften, die eine Inline-Lösung
in `getScripts.py` nicht hätte: Es ist ohne den vollen `ups`-Durchlauf aufrufbar, und es lässt sich
in den Wartungs-Cron hängen.

**Nicht** als Modul unter `scripts/lib/`: `getScripts.py` importiert aus diesem Paket nichts, und
`copy_scripts()` liefert ausschließlich einzelne Dateien aus, kein Verzeichnis. Ein Import würde auf
dem Zielserver mit `ModuleNotFoundError` fehlschlagen.

### Aufbau des Skripts

Kopf im Repo-Stil (Title/Description/Version/Date/Author, danach AGPL-Block), Version `1.0.0`,
Datum `02.08.2026`, Shebang `#!/usr/bin/python3`.

```python
class Severity(Enum):
    OK = "OK"; WARN = "WARN"; FAIL = "FAIL"; SKIP = "SKIP"

@dataclass
class Finding:
    check_id: str
    severity: Severity
    title: str            # kurzes Label für die Reportspalte
    detail: str           # was konkret gefunden wurde
    fix: Optional[str]    # kopierfertiger Befehl, None bei OK/SKIP

@dataclass
class HealthContext:
    root: str = "/"                      # Pfad-Präfix, ermöglicht Trockenlauf gegen ein tmpdir
    home: str = "/root"                  # Ablageort der ausgelieferten Skripte
    repo: str = "/root/myodoo-docker"    # Referenzstand für Versionsvergleiche

CHECKS = [check_maintenance_cron_present, check_logrotate_present, ...]

def run_checks(ctx: HealthContext) -> List[Finding]
def print_report(findings: List[Finding], mode: str) -> None
```

Jeder Check ist eine Funktion `check_xyz(ctx) -> Finding` und steht in `CHECKS`. Ein neuer Check
kostet eine Funktion plus eine Listenzeile.

**Kein Check darf den Report abbrechen.** `run_checks()` fängt jede Exception pro Check ab und
erzeugt daraus ein `SKIP`-Finding mit der Fehlermeldung; die übrigen Checks laufen weiter. Das
entspricht der Degradieren-statt-Abbrechen-Linie im restlichen Repository.

Abhängigkeiten: ausschließlich Standardbibliothek, mit einer Ausnahme — `PyYAML` für das Lesen von
`container2backup.yaml`. Fehlt das Modul, liefert der betroffene Check ein `SKIP`, kein Fehlschlag.

## Aufrufmodi

| Aufruf | Ausgabe |
|--------|---------|
| `server-readiness.py` | Vollständiger Report, alle 13 Checks inklusive der bestandenen |
| `server-readiness.py --brief` | Nur Zeilen ungleich OK, plus Summenzeile |
| `server-readiness.py --quiet` | Wie `--brief`, aber vollständig stumm, wenn alles OK ist |

`--quiet` existiert für den Cron-Einsatz: Cron verschickt nur bei Ausgabe eine Mail, also meldet
sich der wöchentliche Lauf ausschließlich bei tatsächlichem Drift.

**Exit-Codes:** `0` wenn kein FAIL vorliegt, `1` bei mindestens einem FAIL. WARN und SKIP wirken
sich nicht auf den Exit-Code aus.

## Integration

**In `getScripts.py`** (Version `9.8.2` → `9.9.0`, Datum `02.08.2026`): In `main()` direkt nach
`print_install_report()` (Zeile 3933) wird `/root/server-readiness.py --brief` über `run_command`
ausgeführt und die Ausgabe durchgereicht. Fehlt die Datei — etwa auf einem Server, der noch nie
aktualisiert wurde —, wird der Schritt still übersprungen.

Der Exit-Code des Readiness-Checks beeinflusst den Exit-Code von `getScripts.py` **nicht**. Ein
`ups`-Lauf, der Pakete korrekt installiert hat, darf nicht scheitern, nur weil auf dem Server ein
Wartungs-Cron fehlt; bestehende Aufrufer würden sonst brechen.

**Neue Fish-Funktion** `fish/functions/linux/chk.fish` (Version `1.0.0`) ruft
`sudo $HOME/server-readiness.py` auf — der volle Report auf Zuruf, ohne `ups`-Overhead.

**Neue Cron-Zeile** in `scripts/myodoo-maintenance.cron`, wöchentlich montags 06:00:

```
0 6 * * 1 root /root/server-readiness.py --quiet
```

Ausgabe geht über `MAILTO=root` an den Administrator, aber nur bei Befunden. Kein Logfile, kein
Redirect — dieser Job soll gerade *nicht* still in eine Datei schreiben, sonst wiederholt er den
Fehler, den er aufdecken soll.

Der Zeitpunkt liegt bewusst nach dem 04:30-`nightly-cleanup` und deutlich vor dem 14:00-Backup.

## Check-Registry

Alle Checks laufen mit root-Rechten (`ups.fish` ruft `getScripts.py` bereits per `sudo` auf).

| # | check_id | Prüfung | Bewertung |
|---|----------|---------|-----------|
| 1 | `maintenance_cron_present` | `/etc/cron.d/myodoo-maintenance` vorhanden | fehlt → **FAIL** · Fix: `/root/setup-maintenance-cron.sh` |
| 2 | `maintenance_cron_current` | Inhalt gegen `/root/myodoo-maintenance.cron`, siehe Vergleichsregel unten | abweichend → **WARN** · Fix: `/root/setup-maintenance-cron.sh` |
| 3 | `logrotate_present` | `/etc/logrotate.d/myodoo-maintenance` vorhanden | fehlt → **FAIL** · Fix: `/root/setup-maintenance-cron.sh` |
| 4 | `logrotate_coverage` | alle Logpfade der Repo-Vorlage in installierter Config enthalten | fehlend → **WARN** · Fix: `/root/setup-maintenance-cron.sh` |
| 5 | `duplicate_cron_entries` | `crontab -l` (root) **und** fremde Dateien in `/etc/cron.d/` auf `container2backup`, `ssl-renew`, `cleanup-weblogs`, `nightly-cleanup`, `nginx-cert-guard` | Treffer **und** cron.d aktiv → **FAIL** (Doppellauf) · Treffer **ohne** cron.d → **WARN** (Legacy-Setup) · Fix: `crontab -e` bzw. `rm <datei>` |
| 6 | `log_sizes` | Größe der fünf Maintenance-Logs | > 100 MB → **WARN** · > 1 GB → **FAIL** · Fix: `/root/setup-maintenance-cron.sh` bzw. `logrotate -f /etc/logrotate.d/myodoo-maintenance` |
| 7 | `backup_recency` | mtime von `/var/log/container2backup.log` | > 26 h → **WARN** · > 7 d → **FAIL** · Datei fehlt → **WARN** |
| 8 | `backup_config` | `~/container2backup.yaml` vorhanden und per `yaml.safe_load` lesbar | fehlt oder Parse-Fehler → **FAIL** · Fix: `edbk` |
| 9 | `docker_storage_driver` | `docker info` Storage Driver | ungleich `overlay2` → **FAIL** (moby#52431, hohle Images) · Docker nicht installiert → **SKIP** |
| 10 | `nginx_unit_dropin` | `/etc/systemd/system/nginx.service.d/*.conf` enthält `$MAINPID` und `Restart=on-failure` | fehlt → **WARN** (Reload-Falle, Ausfall im apt-Fenster) · nginx nicht installiert → **SKIP** · Fix: `printf`-Befehl für das jeweils fehlende Drop-in (ab v1.1.0; `bootstrap.sh` ≥ 1.10.0 schreibt beide) |
| 11 | `certbot_timer_window` | `systemctl show certbot.timer -p TimersCalendar` gegen das von `bootstrap.sh` gesetzte 03:00-Fenster | Default-Fenster (`00,12:00:00`) → **WARN** · Timer nicht vorhanden → **SKIP** · Fix: `printf`-Befehl für `certbot.timer.d/10-offpeak.conf` (ab v1.1.0) |
| 12 | `script_versions` | Header-Version jedes Skripts aus `copy_scripts()` in `/root` gegen `~/myodoo-docker/scripts/` | abweichend → **WARN** · Fix: `ups` |
| 13 | `backup_disk_space` | Füllstand von `defaults.backup_path` aus `container2backup.yaml` (Vorgabe `/opt/backups`, wie in `container2backup.py`) | > 85 % → **WARN** · > 95 % → **FAIL** |

Die Checks 9 bis 11 stammen aus real aufgetretenen Störungen (containerd-Store-Exportfehler,
nginx-Reload-Falle beim PID-File, nginx-Ausfall während apt-Upgrades).

### Vergleichsregel für Check 2

`setup-maintenance-cron.sh` installiert die Vorlage bei `SCRIPT_DIR=/root` — dem Normalfall —
unverändert (`cat`), schreibt aber bei abweichendem `SCRIPT_DIR` per `sed` die Kommandopfade um
(Zeile 117–122). Ein reiner Byte-Vergleich würde auf solchen Servern dauerhaft falsch anschlagen.

Deshalb zweistufig: Byte-Vergleich als Primärtest; bei Abweichung werden nur die echten Cron-Zeilen
(ohne Kommentare und Leerzeilen) verglichen, wobei der Skriptpfad auf den Basename normalisiert
wird. `WARN` entsteht erst, wenn sich Zeitplan oder Skriptsatz tatsächlich unterscheiden — nicht
wegen eines abweichenden Installationspfads.

### Zu Check 11

`bootstrap.sh` legt `/etc/systemd/system/certbot.timer.d/10-offpeak.conf` an und pinnt den Timer auf
03:00–03:30, frei vom 06:00–07:00-apt-Fenster. Als Fix wird bewusst **nicht** `bootstrap.sh`
genannt: Das ist ein Fresh-Server-Initialisierer und gehört nicht als Reparaturempfehlung auf einen
laufenden Produktivserver. Der Report nennt stattdessen `systemctl edit certbot.timer` und den
konkreten Zielwert in der Detailzeile.

## Ausgabeformat

Angelehnt an `print_install_report()` in `getScripts.py`: `print()` direkt, ASCII-Rahmen,
Farben ausschließlich auf einem TTY (`sys.stdout.isatty()`).

```
============================================================
  Server Readiness Report
============================================================
  [OK]   Maintenance cron    /etc/cron.d/myodoo-maintenance aktiv
  [FAIL] Logrotate           /etc/logrotate.d/myodoo-maintenance fehlt
         -> /var/log/container2backup.log waechst unbegrenzt (412 MB)
         Fix: /root/setup-maintenance-cron.sh
  [WARN] Crontab-Duplikat    'container2backup' auch in crontab -l (root)
         -> Doppelter Backup-Lauf um 02:00 moeglich
         Fix: crontab -e     # alte Zeile entfernen
------------------------------------------------------------
  9 OK · 2 WARN · 1 FAIL · 1 uebersprungen
============================================================
```

Farbzuordnung: OK grün, WARN gelb, FAIL rot, SKIP ohne Farbe.

## Dokumentation

Nachzuziehen: `ReadMe.md` (Skriptliste), `usage/AGENT.md` (Werkzeugtabelle),
`docs/INSTALLATION_GUIDE.md` (beide Sprachfassungen, Skripttabelle und Wartungsabschnitt),
`RELEASE_NOTES.md`.

## Nebenbefund: `scripts/lib/` ist toter Code

Bei der Analyse aufgefallen, **nicht Teil dieser Änderung**: Das Paket `scripts/lib/` (7451 Zeilen)
wird von keiner Datei im Repository importiert. `getScripts.py` verwendet ausschließlich die
Standardbibliothek und `requests`. Der Versionsstand bestätigt den Befund:
`lib/constants.py` steht auf `9.5.0`, `getScripts.py` auf `9.8.2`.

Die mit v8.0 begonnene Modularisierung wurde offenbar nie verdrahtet. Über den Verbleib des Pakets
ist separat zu entscheiden.
