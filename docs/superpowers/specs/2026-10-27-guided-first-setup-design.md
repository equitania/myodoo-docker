# Guided First Setup: cron, fresh-server mode, hardening with a real port change

Date: 27.10.2026 · Status: approved 27.10.2026 (decisions 1–6) · Follows
`2026-10-27-first-run-fresh-server-design.md` (shipped as getScripts 9.34.0).

## Why

The 9.34.0 rollout on two empty Debian 13 hosts worked technically and still
left the operator confused. The end of the first run looked like this:

1. The readiness report said the maintenance cron was missing and told the
   operator to run `setup-maintenance-cron.sh` by hand. The script that had
   just installed everything could have done that itself.
2. The next `ups` opened a three-option dialog about restoring a configuration
   "from the running containers" on a host with zero containers, followed by a
   second yes/no question whose default undid the first answer.
3. The hardening offer listed Firewall, fail2ban and SSH as deviating, offered
   "fix now (only after a lockout check)", and then refused to touch SSH or UFW
   because the port the operator had just entered was not the live port. The
   operator was pointed at six manual steps. The port waited for the operator,
   the firewall waited for the port.
4. The readiness report counted missing backup and update YAMLs as FAIL and
   named a fix (`setup-maintenance-cron.sh`) that had nothing to do with the
   cause (no Odoo instance yet).

The captain's verdict: "the assistant for firewall, fixed IPs and port is not
intuitive, nobody understands it". Decision taken in conversation: the values
are collected in the first-run dialog, the installation runs through without
further questions, and at the very end **one explicit question** applies the
hardening, port change included.

## Decisions

1. **The maintenance cron is installed by getScripts**, not by the operator.
   When `/etc/cron.d/myodoo-maintenance` is missing and Docker is present,
   getScripts runs `setup-maintenance-cron.sh` once and records the result.
   It never re-runs it on a host that already has the file (re-running resets
   `ownerp_cron` edits).
2. **A fresh server is a host with Docker, zero containers and no YAMLs.** In
   that state nothing is "broken": no recovery dialog, no `--from-docker`
   hint, backup/update checks are SKIP, and the run ends with one line naming
   the next step (`wizup`).
3. **The hardening is applied after one question**, on fresh and existing
   hosts alike. The four-option menu ("fix now / show commands / later / mute")
   is replaced by a single yes/no prompt that names what will happen. "Show
   commands" and "mute" remain available through `chk` and `ownerp_mute.py`
   and are named in the prompt's footer, not offered as menu items. Confirmed
   by the captain on 27.10.2026: one flow for all servers, the transition's
   safety (old port stays open until a login on the new port is seen) is the
   same on a host that runs Odoo.
4. **The port change is performed by the tooling, in a transition.** sshd
   listens on the old and the new port at the same time, the new port is
   verified locally, UFW admits both ports from the admin addresses, and the
   old port is closed only after a login over the new port has been observed.
   This replaces "ups never changes the port" and the printed six steps.
5. **Port 22 closes itself.** The transition ends automatically: the next
   `ups` that sees an established SSH session on the new port removes the old
   port from sshd and UFW and says so in one status line. No second question.
   Until then `chk` reports the pending transition and what to do. *(My call,
   derived from "one confirmation": asking "is your second session open?" in
   the same run would be a second question, and it cannot detect a provider
   firewall; an observed login on the new port can.)* Confirmed by the
   captain: no timed rollback, the old port stays open to the admin
   addresses until then, `chk` shows it.
6. **Automatic updates without the nightly reboot.** `hardening_config.yaml`
   ships `auto_reboot: true` (03:30), which collides with the 02:00 backup
   window; the menu asked a separate question, default no. Captain's
   decision: the single question enables security updates and leaves the
   reboot off. `server_hardening.py --apply` gets `--no-reboot`, which
   writes `Automatic-Reboot "false"` regardless of the config; getScripts
   always passes it. Whoever wants the reboot runs
   `python3 ~/server_hardening.py --apply -m auto_updates` by hand, and the
   prompt's footer says so.

## Components

### 1. Maintenance cron during the run (getScripts.py)

`ensure_maintenance_cron(home) -> None`, called in `main()` right after
`run_install_packages()` and before the migrate/noconfig/hardening block.

- Returns silently when `shutil.which("docker")` is None (bootstrap declined
  or failed: the cron would schedule jobs that cannot run) or when
  `/etc/cron.d/myodoo-maintenance` exists.
- Otherwise runs `bash ~/setup-maintenance-cron.sh` via `run_command()`
  (captured in lean mode; the script never prompts, takes no flags) and
  records `record_install("maintenance cron", "installed" | "failed", …)`.
  On failure the detail names the rerun command; the run continues.
- `print_cron_overview()` therefore no longer prints "✗ … not found — run
  setup-maintenance-cron.sh first" on a host with Docker.

### 2. Fresh-server mode

A module-level helper in getScripts.py, `is_fresh_server(home) -> bool`:
Docker binary present, `_any_containers()` is `False` (not `None`), and
neither `~/container2backup.yaml` nor `~/docker2update.yaml` exists.

- `offer_noconfig_recovery()` returns before any output when
  `is_fresh_server()` is true. The existing dialog stays for hosts with
  containers and no YAML (that is the real recovery case).
- `main()` prints, after the readiness report and before "Script completed",
  one status line when `is_fresh_server()`:
  `Noch keine Odoo-Instanz. Nächster Schritt: wizup` (German, like the other
  operator-facing lines of the run).
- `scripts/ownerp_migrate.py` (1.6.0): on the no-CSV/no-YAML path with Docker
  present and `inspect_containers()` empty, print
  `No Odoo instance yet — create the first one with: wizup` instead of the
  `--from-docker` hint. Under `--quiet` this case prints nothing (there is
  nothing to migrate and getScripts prints the next step). Hosts with
  containers keep the `--from-docker` hint under `--quiet` as before.
- `scripts/server-readiness.py` (1.16.0): `check_backup_config`,
  `check_update_config` and `check_backup_recency` return
  `_skip(…, "no Odoo instance yet — wizup")` when Docker is present, the
  config file is missing and `_container_count() == 0`. Zero containers
  *with* a config file is still checked (a configured host whose containers
  are gone is a finding). `check_maintenance_cron_present` and
  `check_logrotate_present` stay FAIL: component 1 makes them pass.

### 3. SSH port transition (server_hardening.py 1.12.0)

New marker file `/root/.config/myodoo-docker/ssh-transition` holding the old
port as a single line (`22`). Written and removed only by server_hardening.

- `--ssh-transition begin`: reads `SSH_PORT` (new) and the live port from
  `sshd -T` (old). No-op with exit 0 when old == new. Refuses (exit 1, reason
  printed) when there are no `ALLOWED_IP_n`, when the live port cannot be
  read, or when the new port is already in use by another process
  (`ss -tlnH sport = :NEW` non-empty and not sshd).
  Then, in order:
  1. If `ssh.socket` is active (Ubuntu socket activation ignores `Port` in
     sshd_config): `systemctl disable --now ssh.socket`,
     `systemctl enable --now ssh.service`. The session in use is a forked
     sshd child and survives. *(My call: the alternative, "refuse on
     Ubuntu", leaves half the fleet on the six manual steps.)*
  2. Writes `Port OLD` and `Port NEW` into `/etc/ssh/sshd_config` (the
     existing rewrite path: every `Port` line replaced, the two lines
     inserted at the position of the first), validated with `sshd -t -f
     <tmp>`, backup, atomic replace, `systemctl reload ssh`, then verifies
     with `sshd -T` that both ports are listed and with a TCP connect to
     `127.0.0.1:NEW` that the banner starts with `SSH-`. Any failure
     restores the backup, reloads, and exits 1 before anything else is
     touched.
  3. Writes the marker, then applies `ufw` (SSH_PORT from the admin
     addresses, 80/443 public, `ufw enable`) plus the transitional rules
     `ufw allow from <ip> to any port OLD proto tcp` per admin address,
     then `fail2ban` and the `ssh` module. The other modules (kernel,
     updates, docker, aide) stay with getScripts' `--apply` calls, which
     keep the Docker-restart logic. *(Changed during implementation: `begin`
     owns the SSH-coupled modules only.)*
- `audit_ssh` / `apply` of the `ssh` module become transition-aware: with the
  marker present, the expected `Port` set is `{OLD, NEW}` and the apply path
  writes both lines; without the marker it is `{NEW}` as today. The audit
  reports the pending transition as `warn` with the detail
  `Portwechsel läuft: anmelden über NEW, dann ups` (one line, no `+N more`).
- `--ssh-transition finish`: requires the marker and an established SSH
  session on NEW (`ss -tnH state established ( sport = :NEW )` non-empty).
  Writes `Port NEW` only, validates, reloads, deletes the transitional UFW
  rules for OLD, removes the marker, prints one line. Without a session on
  NEW it prints `Noch keine Anmeldung über NEW gesehen – Port OLD bleibt
  offen` and exits 0.
- `--ssh-transition status`: prints `none` | `pending OLD -> NEW`, exit 0.
  Used by readiness and getScripts.

### 4. The hardening question (getScripts.py)

`offer_security_hardening()` keeps its entry conditions (TTY, script present,
audit available, `.env` present or offered) and replaces the menu with:

```
Sicherheits-Härtung: Firewall (UFW), fail2ban, SSH weichen ab.

Anwenden heißt: SSH-Port 16667 statt 22, Zugriff nur von 198.51.100.7,
203.0.113.5; Firewall an; fail2ban; automatische Sicherheitsupdates.
Port 22 bleibt offen, bis du dich einmal über 16667 angemeldet hast;
der nächste ups schließt ihn dann.
Diese Sitzung offen lassen. Schaltet der Anbieter eine eigene Firewall
vor (z. B. Hetzner Cloud Firewall), muss Port 16667 dort offen sein.

Härtung jetzt anwenden? (j/N):
```

- The "Anwenden heißt" paragraph is built from the pending areas and the
  `.env`: the port sentence appears only on a pending port change, the IP
  list is the `ALLOWED_IP_n` values, the nightly-reboot question of
  `auto_updates` is gone (decision 6): the clause reads "automatische
  Sicherheitsupdates (ohne nächtlichen Neustart)" and `--no-reboot` is passed.
- `j` → `_apply_hardening()`. With a pending port change it runs
  `server_hardening.py --ssh-transition begin` (which applies everything);
  without one it runs `--apply` for the pending modules as today.
- Anything else → `Später: ups fragt beim nächsten Mal erneut · Details: chk
  · Befehle: python3 ~/server_hardening.py --help · Bereich stummschalten:
  python3 ~/ownerp_mute.py <id> · Nächtlicher Neustart bei Updates:
  python3 ~/server_hardening.py --apply -m auto_updates`.
- `_lockout_blockers()` keeps: no admin IPs, no `SSH_PORT`, live port
  unreadable, peers unreadable, an established peer outside the allowlist.
  It drops: "port change" (now the transition's job) and "ssh.socket active"
  (handled in `begin`). The blocker text for a foreign peer becomes the one
  reason the question is not asked; it is printed with the peer's address
  and the hint to add it to the `.env`.
- At the start of every run with a marker present, `main()` runs
  `server_hardening.py --ssh-transition finish` and records
  `record_install("ssh port", "updated", "22 geschlossen, sshd lauscht auf
  16667")` or `"ok", "Portwechsel läuft – anmelden über 16667, dann ups"`.
- `PORT_CHANGE_STEPS` is deleted. `configure_ssh_access()` drops the
  sentence "Der Port wird hier nur festgelegt, nicht geändert" and the
  six-steps note; it says instead `Die Härtung am Ende der Installation
  stellt den Port um und fragt vorher einmal.`

### 5. Readiness (server-readiness.py 1.16.0)

- SSH hardening check: when `--ssh-transition status` says `pending`, the
  finding is WARN `Portwechsel läuft: anmelden über NEW, dann ups` with fix
  `ups`, replacing the FAIL `Port: 22 (erwartet: NEW) (+15 more)`.
- Fix text of `check_backup_recency` no longer names
  `setup-maintenance-cron.sh` when the cron file exists; it names `wizbk`.

### 6. Documentation

`docs/usage/01-provisioning.md` (first run, fresh server, hardening
question), `docs/INSTALLATION_GUIDE.md` (step order: the port change is part
of the first run), `docs/COMPONENTS.md` (entries for getScripts,
server_hardening, server-readiness, ownerp_migrate), `usage/AGENT.md`
(`--ssh-transition`), `RELEASE_NOTES.md`. The six manual steps leave the
docs; the transition and its `chk` line replace them.

## Settled details

- The transition marker lives next to the `.env` (same directory, root
  only) and is owned by server_hardening.py; getScripts only asks for its
  status.
- Debian's `sshd_config` begins with `Include /etc/ssh/sshd_config.d/*.conf`.
  A drop-in with a `Port` line would win over the main file. `begin` refuses
  when any drop-in sets `Port` and names the file.
- The local banner check uses `socket.create_connection(("127.0.0.1", NEW),
  timeout=5)`; it proves sshd listens, not that the port is reachable from
  outside. The observed login (component 3, finish) proves the latter.
- The transitional `ufw allow from <ip> to any port OLD proto tcp` rules
  are deleted by `finish` by address and port (one `ufw delete` per admin
  IP); ufw rule comments are not used. *(Changed during implementation.)*
- `is_fresh_server()` reuses `_any_containers()` (`docker ps -aq`); a Docker
  daemon that does not answer gives `None`, which is not fresh.
- Non-TTY runs (cron, `ups` from a script) never apply hardening; they print
  one status line as today. `--ssh-transition finish` is the exception: it
  only closes what the operator already opened, so `main()` runs it on every
  run with a marker present, TTY or not.
- getScripts decides between `begin` and `--apply`: it compares `SSH_PORT`
  with `_ssh_listen_ports()` itself. `begin` is called only on a pending
  port change; its own old == new no-op is a safety net, not a code path.
- The marker holds both ports (`22 16667`, one line). `finish`, the audit
  and the expected port set read OLD and NEW from the marker, never from the
  `.env`. If `SSH_PORT` in the `.env` differs from the marker's NEW, `begin`
  and `finish` refuse and name both values; the audit reports it as fail.
- Failure in `begin` after step 2 (ufw, fail2ban or a later module): sshd
  and the marker stay as they are, the step's error is printed, exit 1. The
  old port is still open and admitted, so nothing is lost; the next `ups`
  asks the question again and `begin` resumes (the sshd step is idempotent).
- `finish` counts only established peers on NEW whose address is in
  `ALLOWED_IP_n`; loopback and unlisted peers do not end the transition.
- With the marker present the fail2ban `sshd` jail watches `OLD,NEW`; the
  module writes the list from the marker, as the ssh module writes two Port
  lines. Without the marker it is `${SSH_PORT}` as today.
- `begin` runs the same peer check as the getScripts gate (every established
  SSH peer must be an admin address) and refuses otherwise, so a direct call
  is as safe as the guided one.
- The prompt's pending areas exclude muted ones (as the menu did). With one
  pending area the "Anwenden heißt" paragraph has one clause.
- When `begin` refuses after `j`, getScripts prints the reason, records
  `record_install("hardening", "failed", <reason>)`, continues the run, and
  asks again next time. Nothing is retried in the same run.
- `setup-maintenance-cron.sh` on a host without YAMLs: the backup job exits
  cleanly until `container2backup.yaml` exists (its own next-steps text says
  so), `nightly-cleanup` finds no containers, `ssl-renew` is a no-op without
  certificates. Installing it early is safe.
- `ensure_maintenance_cron(home)` takes the same `home` as `copy_scripts()`
  (`resolve_install_home()`, `/root` in the `sudo su` workflow); the script
  is in the delivery list and is executable after the copy.
- The `ssh.socket` → `ssh.service` switch on Ubuntu is permanent; `Port` in
  sshd_config is the model this toolkit manages.
- The sshd unit is reloaded as `systemctl reload ssh` on Debian/Ubuntu
  (`sshd` is an alias on both; the existing code uses `sshd` and keeps it).
- The banner check connects to `127.0.0.1`; when sshd has a `ListenAddress`
  that excludes loopback, `begin` connects to the first listed address.
- The readiness SSH finding is the audit's own `warn` surfaced unchanged
  (component 5 is a text check, not a second code path).
- Versions: getScripts 9.35.0, server_hardening 1.12.0, server-readiness
  1.16.0, ownerp_migrate 1.6.0; `setup-maintenance-cron.sh` unchanged.

## Consequence for the operator

Fresh Debian 13, README one-liner, answers: proxy no, DNS 1, SSH port 16667
and the proposed admin address, bootstrap `J`. The run installs everything
including the cron and ends with the install report, the cron overview, a
readiness report without FAILs, the line `Noch keine Odoo-Instanz. Nächster
Schritt: wizup`, and the hardening question. `j` → sshd on 22 and 16667, UFW
on, fail2ban on. The operator logs in again on 16667, runs `ups`, sees
`ssh port: updated — 22 geschlossen`. Then `wizup`.

## Testing

- unittest, stdlib, same patterns as `tests/test_getscripts_security_offer.py`
  and `tests/test_getscripts_fresh_server.py`.
- getScripts: `ensure_maintenance_cron` (no docker → silent; file present →
  silent; runs script and records), `is_fresh_server` (three conditions),
  `offer_noconfig_recovery` silent on fresh, next-step line, the new prompt
  text (port sentence only on port change; IPs listed), `j` → transition
  begin, other → later text with the three hints, `_lockout_blockers` without
  the two dropped blockers, finish at run start with both record outcomes.
- server_hardening: `--ssh-transition begin` writes two Port lines and the
  marker; refuses on drop-in Port, on missing IPs, on old == new (no-op);
  rollback when `sshd -t` fails or the banner check fails; `finish` requires
  a session on NEW; `audit_ssh` expects `{OLD, NEW}` with marker;
  transitional UFW rules carry the comment and are the ones deleted.
  `--no-reboot` writes `Automatic-Reboot "false"` with `auto_reboot: true`
  in the config. Subprocesses are mocked; the sshd_config rewrite is tested
  on a temp file.
- readiness: three SKIPs on zero containers without config; FAIL kept with
  config; SSH WARN on pending transition.
- migrate: wizup line with docker and zero containers; silent under `--quiet`.
- A live run in the Apple Container (`gs-trixie-2`) covers everything except
  sshd/UFW (no systemd); the transition itself is verified on the demo host.

## Out of scope

- Opening a provider firewall (Hetzner Cloud Firewall and the like).
- Changing what the SSH module hardens (root login with password stays, see
  memory `server-hardening-setup`).
- IPv6 admin addresses in UFW beyond what `ALLOWED_IP_n` already supports.
- A timed automatic rollback of the transition; the old port stays open to
  the admin addresses until a login on the new port is seen.
