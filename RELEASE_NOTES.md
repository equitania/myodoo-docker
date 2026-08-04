# Release Notes

## Fix Hints You Can Actually Paste (04.08.2026)

### Added
- **scripts/bootstrap.sh v1.11.0**: `--harden` runs only the two systemd hardening steps and nothing else. It exists because of the mistake below: a report can now name one short command instead of printing a `printf` that has to survive copy & paste. `--help` documents both modes; an unknown option is refused instead of silently starting a full bootstrap.
- **scripts/server-readiness.py v1.2.0**: the multi-line fixes introduced earlier the same day were the wrong answer and are gone. Written out, the `nginx unit` fix ran to roughly 180 characters per line including the indent — it wrapped in every terminal, and the wrapped fragments ran back together when copied, which is worse than the one-line hint it replaced. Both fixes are now `bash <repo>/scripts/bootstrap.sh --harden`, and the detail texts were cut to match: the longest line in the report went from ~180 to 89 characters. The lesson is recorded in `print_report()` — a fix that needs several commands belongs in a script that can be named in one line, not spelled out in the report.
- **scripts/bootstrap.sh v1.10.0**: `harden_nginx_service()` also writes `/etc/systemd/system/nginx.service.d/10-reload-mainpid.conf` (`ExecReload=/bin/kill -s HUP $MAINPID`). Until now no script installed it — it existed only as a manual command in the installation guide, so `server-readiness.py` reported `nginx unit` as WARN on every server indefinitely. The stock nginx.org unit reloads via `kill -s HUP $(cat /run/nginx.pid)`, and a preceding `nginx -t` truncates that pid file to zero bytes: the command degenerates to a bare `kill -s HUP`, the reload reports failure, and the old config silently stays live while the new one looks deployed. The empty `ExecReload=` reset line is mandatory — without it systemd appends to the original command instead of replacing it, and the broken `kill` still runs first. Applied to pre-existing installs too, like the other hardening steps.
- bootstrap.sh: the version header said 1.8.0 while carrying the v1.9.0 changes (the bump was missed on 31.07.2026); it now reads 1.10.0.

### Fixed
- **scripts/deploy-nginx-base.sh v1.2.0**: the main `nginx.conf` deploy no longer drops host-specific `load_module` lines. On a server running njs, `nginx -t` failed straight after the deploy with `unknown directive "js_periodic"` — the versioned template carries no `load_module` line (it cannot: dynamic modules like njs, brotli or geoip2 are installed per host), so overwriting `/etc/nginx/nginx.conf` unloaded the module while the vhost using its directives stayed in place. The rollback worked as designed, which means the deploy was simply impossible to complete on that host. `build_main_conf()` now reads the `load_module` lines out of the existing config and prepends them to the template, deduplicated by `.so` path so a re-run does not stack them.
- deploy-nginx-base.sh: a pre-flight `nginx -t` runs before the first write. A config that was already broken beforehand is now reported as such, and the post-deploy failure says so explicitly instead of pointing at an `nginx.conf` that was never the fault.
- **scripts/server-readiness.py v1.1.0**: the `certbot timer` fix hint was pasted verbatim into a drop-in — parenthetical prose and all. It read `systemctl edit certbot.timer   # OnCalendar=*-*-* 03:00:00 (clear OnCalendar= first)`, which squeezes a four-line file, an editor session and a caveat into one comment; what landed in the drop-in was the literal line `OnCalendar=*-*-* 03:00:00 (clear OnCalendar= first)`, without the `[Timer]` header, which breaks the unit. The hint now spells out the exact file content as commands that can be pasted as they stand, states why the empty `OnCalendar=` line is mandatory, and names `bootstrap.sh` as the alternative.
- server-readiness.py: the `nginx unit` fix named `/root/deploy-nginx-base.sh`, which writes no unit drop-in at all — it only repairs an empty `/run/nginx.pid` at runtime. Neither does `bootstrap.sh` write the `ExecReload=$MAINPID` one (it writes only the `Restart=on-failure` drop-in). The hint now emits the `printf` command for whichever of the two drop-ins is actually missing.
- server-readiness.py: `print_report()` renders a multi-line fix with its continuation lines aligned under the first. A fix that has to state a file's exact content cannot be folded into one line without inviting exactly the paste error above.
- **scripts/server-readiness.py v1.1.1**: the two backup checks read a config schema that does not exist. `check_backup_config()` looked for `odoo_instances` and reported "the backup would do nothing" on a server with five databases configured and backing up nightly; `check_backup_disk_space()` looked for `defaults.backup_folder` and fell back to `/home/backup/`, a path no installation uses, so it reported SKIP instead of checking the disk that actually fills up. `container2backup.py` reads `databases` and `defaults.backup_path` (default `/opt/backups`) — the checks now do the same, including the `expandvars`/`expanduser` the backup applies. The wrong keys came from the example in CLAUDE.md, not from the code.
- **CLAUDE.md**: the `container2backup.yaml` example documented `odoo_instances`, `backup_folder`, `db_pass`, `filestore_paths` and `additional_paths` — none of which container2backup.py ever reads (encryption credentials come from `.env`). Replaced with the keys that are real, plus a pointer to `scripts/container2backup.yaml` as the authoritative commented template.

## Readable Update Output (03.08.2026)

### Changed
- **scripts/update_docker_odoo.py v5.4.0**: the update log is legible again. Three defects compounded each other. `read_pipe()` wrote an 80-blank spinner-clear sequence before *every* line, whether a spinner was running or not — in a customer log that shows up as `update odoo...` followed by a field of padding and only then the next entry. Each passed-through container line was additionally stamped with this script's own timestamp on top of the one Odoo already emits, which with a UTC container and a local host reads like a two-hour clock drift. And in filtered mode errors and warnings were printed live *and* repeated in full at the end.
  Child output now passes through verbatim (`classify_line()`): one timestamp — the child's, redundant date dropped, level column aligned. The spinner only runs on a TTY (`IS_TTY`) and erases itself with `\033[K` instead of blank padding. A failure repeats its errors only once at least `ERROR_RECAP_DISTANCE` lines have scrolled past; otherwise the recap would sit directly beneath the line it repeats.
- update_docker_odoo.py: log-level detection no longer guesses. The old cascade searched the entire line for `" ERROR "` and consequently needed a special case for "INFO line that happens to contain the word error". `classify_line()` reads the level from the actual level field of the Odoo (`<ts> <pid> LEVEL <db> …`) or python (`<ts> - LEVEL - …`) format and only falls back to a content check for lines with no recognisable format.
- update_docker_odoo.py: `clean_docker_system()` follows the same step schema. Its prune listing (deleted containers, untagged images) is suppressed and collapsed into `docker system prune ....... ok, 1.207GB reclaimed (4s)` — the reclaimed space is the only part of that output anyone reads.
- update_docker_odoo.py: the closing summary uses the same schema, under a `══ summary ══` header that is distinguishable from a container section at a glance. It previously went through a local helper inside `main()` that hand-assembled `<timestamp> - INFO - <message>` lines with `time.strftime` — the very double-prefix pattern this release removes, only built by hand to dodge the logger's level prefix. That helper is gone, and with it a second function named `print_summary()` carrying a different signature than the module-level one. The redundant `if not args.validate:` guard around the final cleanup (unreachable when false, being inside the `else` of that same condition) is gone too.
- update_docker_odoo.py: per-container output is structured — a `── <container> ──` section header, compact one-line steps (`stop equitania ....... ok (2s)`) for the short docker calls, streamed blocks for `docker build` and the Odoo update runs, and a closing `→ <db>: N warning(s), M error(s), <duration>`. The startup countdown only counts down on a TTY; under cron it sleeps silently instead of writing carriage returns into the log file. `original_level`/`show_full_output` (assigned, never read) are gone.

### Fixed
- **scripts/update_docker_odoo.py v5.4.2**: the update and neutralize runs no longer ask for a terminal (`docker run -it --rm` → `docker run --rm`). This is the cause of the mangled output seen on the server, where every line began in the column the previous one ended in. Only stdout and stderr of the child are redirected into pipes — its stdin stays attached to the real terminal, so `-t` made the docker client put *that* terminal into raw mode for the duration of the run. Raw mode disables ONLCR, the translation of `\n` into CR+LF, so every `\n` written by this script became a bare line feed and the output walked diagonally down the screen. These are one-shot `--rm` batch containers; nobody types into them, and neither `-i` nor `-t` was ever needed.
- update_docker_odoo.py: as a safety net every write to a terminal is now prefixed with a carriage return (`CR`), which repairs the staircase should any other child leave the terminal in raw mode. It is a no-op in normal cooked mode and is never emitted into a log file, where it would only leave stray `^M` bytes. Verified by replaying the raw byte stream through a raw-mode terminal model: 6 staircased lines without the prefix, 0 with it.
- **scripts/update_docker_odoo.py v5.4.1**, from the first verbose run on a live server: `-v` printed `Command completed successfully with no warnings or errors` in front of *every* step line that already said `ok`, plus `Running command: …` in front of every streamed one. Both are gone (the latter moved to `logger.debug`). The wrapper's own log lines now use `HH:MM:SS LEVEL message` indented to the step column when writing to a terminal — the date repeated on every line of a run that takes minutes; a log file still gets the full timestamp, where the date does matter.
- update_docker_odoo.py: the spinner now stops the moment the child produces its first line, instead of continuing to redraw underneath the streamed output. Two writers competing for the same cursor is a race with no upside — once output flows, the output *is* the progress indicator. The spinner's exit path no longer re-clears a line `emit()` has already taken over.
- update_docker_odoo.py: `read_pipe()` reads to EOF instead of polling with `select()`. The old loop gave up as soon as `process.poll()` reported an exit, so lines still sitting in the text buffer at that moment were dropped — and its `raise TimeoutError` ran on a reader thread where nothing could catch it. The real timeout was, and remains, `process.wait(timeout=…)`; the readers now get 5s to drain instead of 1s.
- **Dockerfiles/v18-odoo/odoo.conf, v16-odoo/odoo.conf**: `http_interface` is now set explicitly to `0.0.0.0` instead of being left empty. Behaviourally identical on those versions, but Odoo 19 warns about the unset value (`missing --http-interface/http_interface, using 0.0.0.0 by default, will change to 127.0.0.1 in 20.0`) — and configs get carried over on upgrades. `127.0.0.1` would be fatal in a container: published ports would stop reaching Odoo. Host-side exposure stays restricted by publishing as `127.0.0.1:<port>:8069`, not by the container's bind address. v19-odoo/odoo.conf already had the value; it gained the comment explaining why it must stay.
- Note for existing servers: `sync_build_scripts()` deliberately never syncs `odoo.conf` (it holds per-instance secrets), so these template changes do **not** reach a running system. A server built before this change keeps the old conf in its build folder and must have the line added there by hand before the next `doup`.

## Server Readiness Report (02.08.2026)

### Added
- **scripts/server-readiness.py v1.0.0**: answers "is this server up to date, and what is still missing?" instead of leaving the administrator to check known problems one by one from memory. Runs 13 read-only checks and prints a traffic-light report in which every non-OK finding carries exactly one copy-paste fix command. The gap it closes: `copy_scripts()` in getScripts.py delivers `setup-maintenance-cron.sh` and its two templates to `/root` but never runs or even mentions them — so on servers still driving the backup from a hand-written `crontab -e` entry, `/etc/logrotate.d/myodoo-maintenance` was never installed and `/var/log/container2backup.log` had been growing unbounded since commissioning, with nothing surfacing it.
  Checks: maintenance cron present/current, logrotate present/coverage, duplicate cron entries (root crontab *and* stray `/etc/cron.d` files — with the managed cron active, a leftover entry means two concurrent dumps of the same database), oversized logs, backup recency, backup config, backup disk space, Docker storage driver (moby#52431), nginx systemd drop-in, certbot timer window, script staleness vs. the repository checkout.
  Modes: full report (default), `--brief` (non-OK only), `--quiet` (silent unless WARN/FAIL — for cron). Exit code 1 on any FAIL. `--root/--home/--repo` allow running it against a fixture tree instead of a live server. A check that raises becomes a SKIP finding rather than costing the whole report.
- **fish/functions/linux/chk.fish v1.0.0**: `chk` runs the full report on demand.
- myodoo-maintenance.cron: weekly readiness report Mondays 06:00 via `--quiet`, deliberately **without** a logfile redirect — `MAILTO=root` delivers it only on actual drift, and appending it to an unwatched logfile would repeat the very mistake the report exists to catch.

### Changed
- **getScripts.py v9.9.0**: delivers `server-readiness.py` and prints the readiness report (`--brief`) after the install summary, so every `ups` run ends with the server's actual state. The readiness exit code deliberately does not propagate — an `ups` run that installed its packages correctly must not fail because a maintenance cron is missing.
- setup-maintenance-cron.sh v1.3.0: `server-readiness.py` added to `MANAGED_SCRIPTS` so its absence is reported at install time.
- docs/INSTALLATION_GUIDE.md v1.2.0, ReadMe.md, usage/AGENT.md, fish/README.md: `chk`/`server-readiness.py` documented (DE/EN).

### Known issue (not addressed here)
- `scripts/lib/` (7451 lines) is dead code: no file in the repository imports it, `getScripts.py` uses only the standard library plus `requests`, and the versions have drifted apart (`lib/constants.py` 9.5.0 vs. getScripts.py 9.9.0). The v8.0 modularisation was apparently never wired up. Left untouched deliberately; its fate needs a separate decision.

## nginx Survives apt Upgrades (31.07.2026)

### Added
- **bootstrap.sh v1.9.0**: installs two systemd drop-ins that close a real outage path found on a release server (two outages in two days, 29./31.07.2026). `harden_nginx_service()` writes `Restart=on-failure` + `RestartSec=10` for nginx — the nginx.org unit ships `Restart=no`, so a start failing transiently while `apt-daily-upgrade` swapped glibc resp. openssl left nginx down until someone noticed; a three-second library swap became an outage of hours. `StartLimitBurst=5`/`StartLimitIntervalSec=300` keep it bounded so a genuinely broken config still fails visibly instead of restart-looping. `harden_certbot_timer()` pins the distro `certbot.timer` to 03:00–03:30 — its stock randomized delay of up to 12 h is what put a renewal at 06:51, inside the apt window, and standalone renewals stop nginx. The empty `OnCalendar=` reset line is mandatory: without it systemd *adds* the schedule to the unit's original one instead of replacing it.
- bootstrap.sh: both hardening steps also run on the "already installed" paths of `install_nginx()` / `install_certbot()`, so re-running bootstrap against an existing production server applies them — those are the hosts that need it most.

### Changed
- docs/INSTALLATION_GUIDE.md v1.1.3: the nginx-outage troubleshooting entry (DE/EN) now notes that bootstrap.sh ≥ 1.9.0 sets both drop-ins automatically.
- usage/AGENT.md: new "nginx dies during apt upgrades" guardrail with the symptom (`Connection refused` on 80 *and* 443 while SSH answers) and the automated remedy.

## No More Silently Incomplete Images (31.07.2026)

### Changed
- **build_odoo.py v2.6.0 (v16/v18/v19)**: a module archive that cannot be installed now fails the build instead of only printing a line. Previously the image was built regardless and shipped silently missing that module — a defect that typically surfaces much later as a puzzling `ImportError` or a menu entry that never appears in Odoo. All failed archives are collected and listed together at the end, so one run reveals every problem rather than exposing them one rerun at a time; filenames rejected by the release-file validator are tracked as failures too, since they are just as absent from the image. A circuit breaker aborts the run after 3 consecutive failures (`BUILD_ODOO_FAILURE_LIMIT`) — without it, a release server that disappears mid-build would burn the full ~45 s retry budget on each of several hundred remaining archives. `BUILD_ODOO_ALLOW_PARTIAL=1` is the deliberate opt-out for builds that knowingly tolerate missing modules.
- build_odoo.py: the closing statistic counts successful downloads only. It previously incremented per *attempt*, so `Files downloaded: 407/407` was printed even when archives had failed.
- docs/INSTALLATION_GUIDE.md v1.1.2: new troubleshooting entry (DE/EN) for the aborted build with the archive list, incl. `BUILD_ODOO_FAILURE_LIMIT` and the `BUILD_ODOO_ALLOW_PARTIAL` opt-out.
- usage/AGENT.md: new "Incomplete images" guardrail; the kernel-vs-module asymmetry noted earlier no longer applies.

## Build Resilience Against Release-Server Downtime (31.07.2026)

### Added
- **build_odoo.py v2.5.0 (v16/v18/v19)**: downloads now survive a briefly unavailable release server instead of aborting the whole image build. Transient failures (connection refused/reset, timeouts, HTTP 408/425/429/5xx) are retried up to 5× with exponential backoff (3 s, 6 s, 12 s, 24 s, capped at 60 s — ~45 s total), which comfortably covers a systemd restart of the web service on the release host. Permanent failures (404/403) still fail immediately rather than wasting four retries on a file that does not exist. Every attempt is logged with its cause and the pending delay (flushed immediately), so a waiting build is visible in the Docker build output instead of appearing to hang; the final message names the unreachable host and points at `systemctl status nginx`. Tunable via `BUILD_ODOO_RETRIES` and `BUILD_ODOO_RETRY_BACKOFF`. urllib3's own retry layer is disabled for these requests so the logged attempt count matches reality.

### Changed
- docs/INSTALLATION_GUIDE.md v1.1.1: two new troubleshooting entries (DE/EN) — aborted builds with `Release server '…' could not be reached` (incl. the caveat that only a failed *kernel* download aborts, while a failed *module* download silently yields an incomplete image), and nginx staying dead after an apt upgrade because it was restarted mid-swap of glibc/openssl while the nginx.org unit ships `Restart=no`, with the `Restart=on-failure` and `certbot.timer` drop-ins as the fix.
- usage/AGENT.md: new "Release-server downtime" guardrail covering the retry behaviour, both env vars, and the kernel-vs-module abort asymmetry.

## Proxy Customer Support & Multi-ZIP Builds (16.–17.07.2026)

### Added
- **docs/INSTALLATION_GUIDE.md v1.1.0**: new chapter 18 "Operation Behind an HTTP Proxy" (DE/EN) — initial installation behind a proxy (session env before bootstrap), the four locations `--proxy-check` writes with their activation points, `docker2update.yaml` `defaults.proxy` + `pre_build_files`, proxy peculiarities (fastfetch, uv, `no_proxy` for internal domains), verification block and troubleshooting table. Distilled from a real proxy-customer deployment.
- usage/AGENT.md: agent capability card for the admin toolkit (LLM-facing usage reference).

### Changed
- Repo hygiene: untrack internal planning artifacts, prune legacy `.gitignore` entries.

### Fixed
- getScripts.py v9.8.0: `--proxy-check` now really writes the Docker daemon systemd drop-in (`docker.service.d/http-proxy.conf` + daemon-reload; deliberately no automatic restart — that restarts all containers) as long documented by update_docker_odoo.py. fastfetch deploy is proxy-aware: the `publicip` module (raw sockets, ignores `http_proxy`, hung every login behind silently-dropping firewalls) gets a 1 s timeout globally and is stripped entirely on hosts with a configured proxy marker; `--proxy-check` re-deploys the config immediately.
- getScripts.py v9.8.1/v9.8.2: no more warning noise from `uv self update` on package-manager installs — the command result is classified instead of guessing from the binary path (unreliable: `pip install --user uv` lands in `~/.local/bin`, the standalone installer's location; pip-wheel and homebrew builds also word the refusal differently). Known "cannot self-update" messages log as INFO skip; real failures keep the WARNING with stderr.
- bootstrap.sh v1.8.0: stage the overlay2 pin on existing Docker installs too (previously fresh installs only).
- build_odoo.py v2.4.0 (v16/v18/v19): extract **all** `*custom_modules.zip` archives from the build context — a second customer-specific archive (e.g. `xy_custom_modules.zip`) was copied into the image but silently never extracted. The generic `custom_modules.zip` is processed first so customer-specific archives can override its modules. Dockerfile template comment widened to `*custom_modules.*`.

## Deployment Tooling, Docker-29 Hardening & Installation Guide (15.–16.07.2026)

### Added
- **docs/INSTALLATION_GUIDE.md**: bilingual (DE/EN) step-by-step guide for system administrators — fresh server → two production Odoo systems (live/test) behind nginx with Let's Encrypt, updates (`edup`/`doup`) and backups (`edbk`/`dobk`). Covers all repository scripts (reference table with usages), the complete fish alias/function reference, and a troubleshooting section built from real rollout lessons (Docker ≥ 29 containerd-store export bug incl. orphaned-overlay-mount aftermath, nginx pid-file reload trap, NAT bind-IP, split-horizon DNS, `db_sslmode`, `127.0.0.1:` port binding). ReadMe.md links the guide prominently and gains a "Scripts at a Glance" usage table (DE + EN).
- ngx-conf-wizard.sh v1.0.0/v1.1.0: interactive YAML config builder for nginx-set-conf — all 19 templates, entry-by-entry loop with validation, append/overwrite with backup, local-IP display with warning on non-local bind IPs (NAT), optional deploy at the end.
- pg-local-deploy.sh v1.2.0: optional self-signed SSL for the PostgreSQL container (server.crt/server.key in PGDATA, RSA-4096, 10 years, idempotent) — mirrored in the Semaphore playbook (`pg_ssl` extra var).

### Changed
- pg-local-deploy.sh v1.2.1: version prompt shows a current example (16.14) plus the Docker Hub tag-search URL.
- fr-local-deploy.sh: default volume base `/opt/fast-report`, current image-tag example.

### Fixed
- bootstrap.sh v1.7.0: pin the classic overlay2 storage driver on fresh Docker ≥ 29 installs (`/etc/docker/daemon.json`) — the containerd image store's export is broken for large builds (moby/moby#52431: `ref … locked: unavailable`, or hollow images missing even `/bin/sh`). Existing installs are never switched automatically; a warning with the manual remediation path is printed instead.
- odoo.conf v16/v18/v19: revert `db_sslmode` to `prefer` — `require` (from the 14.07 security review) broke database creation against every standard PostgreSQL container without SSL.
- getScripts.py v9.7.3: install for root in sudo-spawned root shells (`SUDO_COMMAND` detection) — operators working via `sudo su` previously got the fish config installed into the admin user's home instead of `/root`.
- deploy-nginx-base.sh v1.1.0: surface nginx reload failures (previously swallowed — old config silently stayed live) and repair an empty `/run/nginx.pid` from systemd's MainPID before reloading; internal `SCRIPT_VERSION` aligned with the header.

## Repository Security Review & Hardening (14.07.2026)

Full-repository security review (Python, Shell/Fish, Docker/config) with fixes applied across all severities.

### Added
- pg-local-deploy.sh / fr-local-deploy.sh: password input now shows one `*` per typed character (with backspace), so the number of entered characters is visible while the secret itself stays hidden (`_read_masked`). Same masking added to fr-local-deploy.sh registry-token input and restore-zip.sh password fallback.

### Changed
- fr-local-deploy.sh **[CRITICAL]**: removed the shared "baked default" secrets (JWT signing key, MD5 admin hash, bcrypt superuser hash) — they were identical across all deployments and would be an auth-bypass if the repo is readable. When no override and no existing appsettings.json is present, admin/superuser passwords and the JWT key are now generated **randomly per deployment** (`secrets`) and shown once in the final banner. When the superuser hash is needed and `bcrypt` is missing from the system Python, the script now provisions it automatically in a cached **uv venv** (`~/.cache/fr-local-deploy/venv`) instead of aborting.
- update_docker_odoo.py v5.3.1 **[HIGH]**: `db_password_via_env` now defaults to **true** — the DB password goes via `-e PGPASSWORD` instead of the `docker run` argv (previously visible in `ps aux`). Example YAMLs document the flag.
- bin/boot v2.2.0/v2.3.0 (v16/v18/v19): container entrypoint now whitelists `start|update|neutralize`; arbitrary arguments are no longer executed as root.
- build_odoo.py v2.3.0 (v16/v18/v19): `unzip` runs without `shell=True` (+ CSV filename validation); TLS downloads enforce `cert_reqs=CERT_REQUIRED` with certifi.
- odoo.conf (v16/v18/v19): `db_sslmode = require`; v19 gains a `proxy_access_token` placeholder. Dockerfiles: `ADD` → `COPY`.
- syspatch.fish v1.3.0: dropped the unconfirmed `docker volume prune -f` (could irreversibly delete data volumes of stopped containers); prunes only dangling images now.

### Fixed
- fr-local-deploy.sh **[CRITICAL/HIGH]**: appsettings.json (contains the JWT key in cleartext) now `chmod 0600`; `docker login --password-stdin` and stdin/WGETRC-based basic auth instead of credentials in argv; whitelist validation for container name and image tag (Compose-YAML injection).
- pg-local-deploy.sh v1.1.0 **[MEDIUM]**: whitelist validation for DB user/name; compose file created via `umask 077` (no world-readable TOCTOU window); docker-run fallback uses `--env-file` instead of `-e` for the password.
- container2backup.py v4.7.1 **[HIGH]**: the backup password is masked in log output — the gpg-less 7z fallback no longer writes the cleartext password into the cron log.
- restore-zip.sh v2.1.0: DB password resolved from `PGPASSWORD` env → positional arg (warns) → masked prompt, instead of a plain positional argument visible in `ps aux`; GPG-decrypted dump written with `umask 077`.
- getScripts.py v9.7.2 / proxy_config.py: `no_proxy` is validated before being written into the sourced fish startup file (command-injection); missing `requests.get` timeouts added; predictable `/tmp` download paths replaced with `tempfile.mkstemp`; jammy APT repo over HTTPS.

## Live Version Checks & Fail2Ban Audit Polish (11.06.2026)

### Changed
- getScripts.py v9.5.0: all GitHub/PyPI latest-version lookups (ctop, fastfetch, zoxide, bat, 7zip, pypi_*) now query the live API first; the 24h cache is only used as a fallback when the API is unreachable. Previously `ups` was blind to releases published within a day (e.g. ctop 0.8.7 was ignored while 0.8.6 was still cached). Resilience preserved, freshness restored; GitHub calls without a timeout now use `timeout=15`.
- server_hardening.py v1.8.0: Fail2Ban UFW bans (banaction=ufw, rules commented `by Fail2Ban`) are now reported as **info** with banned IP and jail name instead of "Unbekannte Regel" warnings — the per-ban noise was hiding real configuration drift. All other unexpected UFW rules keep warning as before.

### Fixed
- hardening_config: the four nginx Fail2Ban jails pointed at `/var/log/fail2ban_nginx-*.log` — files nothing ever writes. `--apply` therefore auto-disabled them on every run while the audit kept counting them as errors (unfixable loop). They now parse the real host-nginx logs (`error.log` / `access.log` for bad-request). security_headers: dropped deprecated `X-XSS-Protection` (removed from security.conf v1.3), added `Content-Security-Policy` + `Permissions-Policy` so the audit matches the deployed header policy.

## nightly-cleanup in Standard-Cron (11.06.2026)

### Changed
- nightly-cleanup.sh is now part of the standard maintenance setup: deployed to `/root` by getScripts.py (v9.4.0) and scheduled daily at **04:30** in `/etc/cron.d/myodoo-maintenance` (setup-maintenance-cron.sh v1.2.0) — deliberately after the 02:00 backup window so a container restart can never hit a running backup. Log rotation was already in place. The installer now also warns when the legacy standalone `/etc/cron.d/nightly-cleanup` (old manual instructions, 03:00) is present, which would cause duplicate runs. NIGHTLY_CLEANUP.md (DE+EN) rewritten for the standard path; the manual `/usr/local/bin` install remains documented as an alternative.

## Script Review Follow-up (11.06.2026)

### Added
- restore-zip.sh v2.0.0: Multi-format restore with automatic detection — supports every format container2backup.py produces: `.zip`, `.7z`, `.7z.gpg` (GPG decrypt with passphrase prompt), `.tar.gz`, `.tar.zst`. Previously only `.zip` was supported although `7z` is the backup default. New guards: required inputs are rejected when empty (an empty DB name could previously expand `rm -rf` to the backup root), and the cleanup step can no longer delete `/opt/backups/docker/` itself.

### Fixed
- nginx-cert-guard.py v1.1.0: bracketed IPv6 listeners (`[::1]:443`) are no longer misreported as unresolvable (would have quarantined healthy vhosts); rollback now matches quarantined files by exact path instead of `server_name` (a duplicate server_name could restore vhosts quarantined manually before the run); quarantine report now reads the domain from the renamed file (was read from the no-longer-existing pre-rename path).
- server_hardening.py v1.7.0: banner printed v1.5.0 while the header said v1.6.0 (now a single `SCRIPT_VERSION` constant); defective/empty YAML config now exits with a clear message instead of an `AttributeError` traceback; changing the SSH port now warns loudly when the new port is missing from the UFW rules (lockout guard).
- ssl-renew.sh v1.3.0: if even the final nginx fallback start fails, the script now exits 2 with a clear error instead of exiting 0 with nginx down.
- nightly-cleanup.sh v1.1.0: `POSTGRES_PATTERN` anchors the `db` tokens (`^db-`, `-db$`) — bare `-db`/`db-` also matched containers like `redis-db-cache`; `/var/log/nightly-cleanup.log` added to myodoo-maintenance.logrotate (grew unbounded).
- getScripts.py v9.3.1: removed ghost entry `container2backup_zstd.py` from `copy_scripts()` (file no longer exists).

### Removed (orphaned)
- `config/backup_config.yaml`, `config/backup_credentials.yaml`(+`.example`): leftovers of a pre-`.env` architecture, read by no script; the credentials file was tracked despite its own "NEVER commit" notice (placeholder only, no leak). `.gitignore` now blocks `config/backup_credentials.yaml` permanently.
- `scripts/docker-clean-logs.sh`: unversioned 4-liner with unquoted `rm $(...)`; the `cleandlog` alias never used it (truncates log files directly).

### Docs
- README_BackUp.md, ReadMe.md, .env.example: encryption sections rewritten for GPG/`.7z.gpg` (incl. `gpg -d` restore steps and gnupg dependency), version references refreshed, `db_password_via_env` documented, `pip3 install` replaced with PEP-668-compliant apt packages.

## Security Hardening & IONOS Compatibility (11.06.2026)

### Fixed
- getScripts.py v9.2.0: Fish OBS repo setup no longer requires gnupg (minimal images like IONOS Debian 13 ship without it). The signing key is written as ASCII-armored `.asc`; a failed key download no longer leaves apt broken system-wide (rollback + self-healing of half-configured repos + fallback to the Debian fish package).
- bootstrap.sh v1.6.0: Generates the `en_US.UTF-8` locale on minimal images (IONOS) — eliminates the perl/apt `setlocale` warnings on every command.
- Dockerfiles/v18-odoo: `FROM` pointed at `myodoo/prepare-v16:25.02.24-3.11.11` (copy-paste error). Now `myodoo/prepare-v18:26.05.19-3.13.13`; v19 raised to `myodoo/prepare-v19:26.05.19-3.13.13`.

### Security (project audit follow-up)
- getScripts.py v9.3.0 + scripts/lib: starship, zoxide and uv are no longer installed via `curl … | sh` pipes running unreviewed remote code as root — they now use official GitHub release binaries/.deb packages (same pattern as ctop/fastfetch/7zz). Fisher bootstrap is pinned to the latest tagged release instead of the moving main branch. Fish OBS repo URL switched to https (existing http `.list` files are migrated on the next run).
- container2backup.py v4.6.0: Encrypted backups now use GPG (AES-256, passphrase via fd) producing `.7z.gpg` — the former `7zz -p<password>` exposed the backup password in the process list. Decrypt: `gpg -d backup.7z.gpg > backup.7z`. Falls back to 7z AES (with a loud warning) when gnupg is missing. The `rsync.commands` YAML list now only accepts the rsync binary (no generic root command runner).
- update_docker_odoo.py v5.2.0: New per-container option `db_password_via_env: true` passes the DB password via `PGPASSWORD` environment (docker `-e` forwarding) instead of `--db_password=` in argv (visible in `ps`). Requires images built from 11.06.2026 (boot scripts now whitelist PGPASSWORD across `su`); default remains the legacy argv mode for older images.
- restore-zip.sh v1.4.0: `PGPASSWORD` is forwarded via the environment instead of appearing in the `docker exec` argv.
- requirements: CVE-affected pins raised in prepare-18/prepare-19 (Jinja2 3.1.6, Werkzeug 3.0.6, Pillow 10.4.0/11.3.0, requests 2.32.5, urllib3 1.26.20/2.5.0) and custom libs modernized (pycryptodome 3.23.0, oauthlib 3.3.1, bleach 6.4.0, pandas 2.2.3, numpy 1.26.4, holidays 0.69, xmltodict 0.15.1, pypandoc 1.17, python-docx 1.2.0, pdfminer.six 20260107, msal 1.37.0). Root requirements.txt: requests>=2.32.0, PyYAML>=6.0.2.

## nginx OCSP Stapling Removal (28.05.2026)

### Changed
- nginx/nginx.conf v1.4: Disabled `ssl_stapling` / `ssl_stapling_verify` (with explanatory comment). Let's Encrypt retired OCSP in May 2025; renewed LE certificates no longer carry an OCSP responder URL, so `nginx -t` started logging one warning per certificate at every startup/reload and stapling did nothing useful. Re-enable only if switching to a CA that still issues OCSP-bearing certificates. To apply on a server: `ups` + `sudo /root/deploy-nginx-base.sh` (which will back up the prior nginx.conf before installing the new one).

## Maintenance Cron Follow-up (28.05.2026)

### Changed
- setup-maintenance-cron.sh v1.1.0: After installing `/etc/cron.d/myodoo-maintenance` the script now scans root's user-crontab (`crontab -l -u root`) for legacy entries referencing the managed scripts (`container2backup.py`, `ssl-renew.sh`, `cleanup-weblogs.py`, `nginx-cert-guard.py`) and warns about them — these would otherwise run **in addition** to the cron.d jobs (e.g. backups firing twice a day). Read-only: the script never edits the user crontab (it may contain unrelated operator entries); removal is left to the operator via `sudo crontab -e -u root`. README_BackUp.md updated accordingly.

## nginx Base Rollout & Config Hygiene (27.05.2026)

### Added
- deploy-nginx-base.sh v1.0.0: Rolls out the shared nginx files every vhost depends on — `nginxconfig.io/security.conf`, `nginxconfig.io/general.conf`, `html/custom_50x.html` — to `/etc/nginx`, so a missing `include` can no longer make `nginx -t` fail and take the whole server down on rollout. Also replaces `nginx.conf` safely: backup + `nginx -t` + automatic rollback on failure. Idempotent; `--no-main-conf`, `--dry-run`, `--src`/`--dest`. Deployed to /root by getScripts.py; referenced as a next step in bootstrap.sh (v1.4.2).

### Changed
- nginx/nginxconfig.io/security.conf v1.3: removed deprecated `X-XSS-Protection`; activated an Odoo-tuned `Content-Security-Policy` (ws/wss for longpolling, `frame-ancestors 'self'`). This file is now the single source of truth for security headers.
- nginx/nginx.conf v1.3: removed the duplicate security-header block (headers are not inherited once a child block sets its own — the http-level copy was dead and divergent) and the dead `error_page /404.html` / `/50x.html` directives (vhosts set `/custom_50x.html` themselves).
- nginx/nginxconfig.io/general.conf v1.1: removed the redundant per-vhost `gzip` (it is configured globally in nginx.conf).

## nginx Outage Protection (27.05.2026)

### Added
- nginx-cert-guard.py v1.0.0: Prevents a full nginx outage when a customer's (sub)domain stops pointing at the server. `--reconcile [--start]` brings nginx up at renewal and quarantines only the broken vhost (missing `ssl_certificate` file, or an old `listen <domain>:443` whose host no longer resolves) instead of letting one bad vhost block the whole server; includes a mass-failure guard with rollback so a global fault never causes a blind shutdown. `--check [--apply]` proactively detects drifted domains via DNS and disables them after `GUARD_FAIL_THRESHOLD` confirmed runs (guards against DNS glitches / Cloudflare-fronted domains via a confirmation counter + `GUARD_IGNORE_DOMAINS`). `--list` / `--restore <domain>` for inspection and recovery. SMTP alert mail via `smtplib`.
- Maintenance cron: daily proactive `nginx-cert-guard.py --check --apply` at 23:50, just before the cert renewal; `/var/log/nginx-cert-guard.log` added to logrotate.
- `.env.example`: `ALERT_*` (SMTP relay) and `GUARD_*` (server IPs, ignore list, thresholds) keys.

### Changed
- ssl-renew.sh v1.2.0: nginx is restarted via `nginx-cert-guard.py --reconcile --start` (post-hook + safety net) instead of a bare `systemctl start nginx`, so a single broken vhost can no longer take the whole server down. Falls back to `systemctl start nginx` when the guard is absent.
- getScripts.py: deploys `nginx-cert-guard.py` to /root.

## Server Provisioning & Hardening (27.05.2026)

### Added
- bootstrap.sh v1.4.x: Out-of-the-box initializer for fresh Debian 12/13 and Ubuntu 20.04/22.04/24.04/26.04 — installs Docker CE, nginx, certbot, UFW (disabled), fail2ban baseline, and unattended-upgrades; self-installs to `/opt`, idempotent, every stage toggleable via env var
- server_hardening.py v1.5.0: Config-driven audit/apply hardening tool (`hardening_config.yaml`) covering UFW, fail2ban, SSH, sysctl, sysctl_persist, kernel module blacklist, Docker daemon, auto-updates, auditd, AIDE, nginx, and port modules; lockout-safe SSH swap (atomic after `sshd -t`), dynamic `ALLOWED_IP_<n>` allowlist, detailed `--help`
- dist-upgrade-debian.sh v1.0.0: Guided, phased Debian major release upgrade (e.g. bookworm → trixie) with apt-source backup and reboot prompt; refuses to run on Ubuntu
- setup-maintenance-cron.sh v1.0.0 + myodoo-maintenance.cron/.logrotate: Declarative `/etc/cron.d/` maintenance jobs (backup 02:00/14:00, daily cert renewal, daily DSGVO weblog purge) plus weekly logrotate; idempotent with `--remove`
- bootstrap.sh: certbot (Let's Encrypt client) installation step

### Changed
- ssl-renew.sh v1.1.0: Renew via certbot `--pre-hook/--deploy-hook/--post-hook` — nginx is only bounced when a certificate is actually due (no more unconditional weekly downtime); own logging and an "nginx never left down" safety net
- syspatch.fish v1.2.0: Rebuild the AIDE baseline after a system update; pass `--config` explicitly (AIDE 0.18+ on Debian trixie ships no compiled-in default config)
- getScripts.py v9.0.8/v9.0.9: Switch the 7-Zip download to the `ip7z/7zip` GitHub mirror (fixes 404 on stale pinned URLs), robust 7zz version parsing, and restore the default-shell prompt
- getScripts.py: copy_scripts deploys the new maintenance scripts/templates to `/root`

### Fixed
- container2backup.py v4.5.1: Guard the path-issue confirmation prompt with `sys.stdin.isatty()` — under cron (no TTY) it now aborts cleanly instead of raising `EOFError`
- .gitignore: Remove a corrupted line so `scripts/.env` is reliably ignored
- dist-upgrade-debian.sh: Validate codenames against `^[a-z][a-z0-9]*$` before interpolating into the sed rewrite
- server_hardening.py v1.4.1: Apply AIDE excludes even when a database already exists (prevents the 30+ min Docker-host scan); literal numeric strings no longer int-cast into Docker daemon.json

## Security Hardening (21.04.2026)

### Added
- cleanup-weblogs.py v2.0.0: Atomic log rotation via `nginx -s reopen` (SIGUSR1), fcntl lock against concurrent runs, opt-in cache clearing via `--clear-cache`, backup cleanup restricted to `*.bak` files

### Changed
- container2backup.py v4.5.0: Validate `db_name`, `db_user`, `sql_container`, `data_container` against `[A-Za-z0-9_.-]+` at config-load time; skip invalid entries instead of aborting
- getScripts.py v9.0.7: Cache layer migrated from pickle to JSON

### Fixed
- [H1] container2backup.py: Eliminate all `shell=True` subprocess calls (filestore extract, zip/gzip/zstd compression) — replace with list-form arguments, `Popen` pipelines, and `cwd=` parameter. Closes command-injection vector via YAML-controlled identifiers.
- [H2] scripts/lib/cache.py + getScripts.py: Replace unsafe `pickle.load` with `json.load`; enforce cache-key allowlist (`[A-Za-z0-9._-]+`) to prevent path traversal from cache directory. Existing pickle caches self-heal on first read.

## Security Hardening (17.03.2026)

### Added
- HEALTHCHECK directive for all Odoo Dockerfiles (v16, v18, v19) using wget --spider on /web/health

### Fixed
- [H1] restore-zip.sh: Fix shell injection via unquoted variables, broken bash syntax on lines 205/233, add input validation and set -euo pipefail
- [H2] check_dockerimage_odoo.py: Replace os.system() with subprocess.run() argument lists, add regex validation for Docker image references
- [H3] container2backup.py: Replace shell=True rsync execution with shlex.split() argument parsing
- [H4] getScripts.py, proxy_config.py, dns_optimizer.py: Replace all `echo | sudo tee` shell injection patterns with subprocess.run(input=) (8 locations)

## Version 9.0.0 (26.02.2026)

### Changed
- Migrate CLI tool manager from pipx to uv (`uv tool install/upgrade`)
- Auto-update uv on every run (`uv self update`)
- Auto-upgrade all installed uv tools on every run (`uv tool upgrade --all`)
- Replace all pipx functions with uv equivalents in getScripts.py and package_manager.py
- Rename packages.txt section header from `# PIPX packages` to `# UV tool packages`
- Remove pipx from system packages (uv is installed via curl, not apt)

### Fixed
- Backward compatibility: parser still accepts legacy `# PIPX packages` section header

### Migration
- pipx is automatically uninstalled if still present (after uv tools are installed)
- All pipx-managed tools are migrated to uv tool management
