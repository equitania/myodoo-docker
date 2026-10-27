# First run on a fresh server — Design

*27.10.2026 · status: specified, not yet implemented*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

---

## Why this exists

On 27.10.2026 the toolkit was rolled out onto an empty Debian 13 server the
way the README's one-liner says: install git, clone, copy `getScripts.py`,
run it. The run ended with "Script completed successfully!" and the server
was not usable:

- **Fish was installed and the script did not notice.** The operator's SSH
  session carries a German locale (`apt` answered in German), and Fish 4.9
  localises its version line: `fish, Version 4.9.3` with a capital V.
  `is_fish_installed()` matches `version (\d+\.\d+\.\d+)` case-sensitively,
  so it returned "not installed", `install_fish_if_needed()` fell through its
  final `return False, False` without a word, no Fish configuration was
  copied, no shell change was offered, and the closing
  `source ~/.config/fish/config.fish` failed. Reproduced in a Debian 13
  container: under `LANG=C` the line reads `version`, under `de_DE.UTF-8` it
  reads `Version`, exit code 0 both times.
- **Every privileged command is spelled `sudo …`**, although the script runs
  as root. A minimal Debian without the `sudo` package (the normal state of
  a root-only install) fails every apt call and aborts in `install_packages()`
  — reproduced in the same container. The demo server happened to have
  `sudo`; the next one may not.
- **The hardening check ran before the packages it needs.**
  `offer_security_hardening()` created the `.env`, then
  `server_hardening.py --json` ignored it because `python3-dotenv` is
  installed by `install_packages()`, which runs later. The operator saw
  `Härtungs-Audit nicht möglich: ssh.port invalid: ''` for a file written
  two lines above.
- **Nothing recognised a fresh server.** `ownerp_migrate.py` recommended
  `--from-docker` on a host without Docker; the readiness report listed six
  FAILs with `edbk` hints for a host that cannot run a backup; the one step
  our own installation guide puts first — `bootstrap.sh` (Docker, nginx,
  certbot, UFW, fail2ban, unattended-upgrades, the Python packages) — was
  never mentioned.
- **The `.env` was pre-filled and confirmed with a default "J"**: port 22 and
  the address of the current SSH session. The operator wanted to be asked
  for a fixed port and a list of admin addresses at the first installation,
  not to repair the file afterwards.
- **Noise**: three `ERROR` lines for a missing `batcat` (the expected state
  on a fresh host), three `7zz` warnings, and "bat 0.25.0 is older than
  0.26.1" right after apt installed it.
- **The README's one-liner ends in `source ~/.config/fish/config.fish`
  inside a bash chain.** bash cannot source a Fish file; the line fails even
  after a perfect run.

## Decisions

Taken in the conversation, with the alternatives that were rejected:

1. **`getScripts.py` offers to run `bootstrap.sh` itself on a fresh server**
   and runs it when the operator agrees. *Rejected:* only pointing at it —
   that is what the installation guide already does, and the operator did
   not read it; the README's own one-liner skips it.
2. **The first-run dialogue asks for the SSH port and the admin addresses**,
   as a third block after proxy and DNS, and writes the `.env` right there.
   *Rejected:* keeping the derived-values offer as the only path (it is a
   confirmation, not a question — the operator's complaint); asking inside
   the hardening offer later in the run (that offer is skipped without a
   TTY and never fires when the .env is muted).
3. **Order of `main()` changes so that packages precede every check that
   needs them.** *Rejected:* making `server_hardening.py` tolerate a missing
   `python3-dotenv` — the audit would still be wrong, only quieter.
4. **Version probes run under `LC_ALL=C` and match case-insensitively.**
   *Rejected:* fixing the one regex only — every other `--version` parser in
   the script has the same exposure, and the operator's locale is not ours
   to choose.
5. **`sudo` is dropped when running as root**, not installed. *Rejected:*
   installing the `sudo` package as a base dependency — it changes the
   host's security surface for a spelling problem in our own script.

## Components

### 1. Locale-safe version probes (getScripts.py)

- A helper `probe_output(argv, timeout)` runs the command with
  `env={"LC_ALL": "C", "LANG": "C"}` merged over `os.environ` and returns
  stdout+stderr, or `None` when the binary is missing. `is_fish_installed()`,
  `is_zsh_installed()`, `is_starship_installed()`, `get_bat_version()` and the
  7-Zip probe use it. Version regexes get `re.IGNORECASE`.
- `install_fish_if_needed()` loses its silent fall-through: the Debian branch
  ends with an explicit `record_install("fish", "failed", "apt reported
  success, but `fish --version` gave no version — see ~/getscripts.log")`
  whenever apt succeeded and the probe did not. On success
  `record_install("fish", "installed"|"ok", "v<version>")`, so the install
  report names the shell on every run — today it is the one component the
  report never mentions.

### 2. Root without sudo (getScripts.py)

- `run_command()` strips a leading `sudo ` from the command and from every
  segment after `&&`, `||`, `;` and `|` when `os.geteuid() == 0`. The
  commands are our own constants; the transformation is a regex on word
  boundaries (`(^|[;&|]\s*)sudo\s+`), applied before the shell/split
  decision. A unit test pins `sudo apt update` → `apt update` and
  `curl … && sudo mv a b` → `curl … && mv a b` as root, and no change as a
  normal user.
- The one direct `subprocess.run(["sudo", "tee", repo_list_path], …)` in
  the Fish installer becomes a Python write of the file (root) or the
  existing `sudo tee` (non-root), through a small `write_system_file()`.
- `is_root_or_has_sudo()` is unchanged: root is root.
- Base packages: before the Fish setup, `ensure_base_packages()` installs
  `curl` and `ca-certificates` when `shutil.which("curl")` is None (git is
  present by construction — the repository was just cloned). The Fish key
  import, Starship and uv all need curl; today they fail one after another
  with "curl: not found" in the log.

### 3. Order of `main()` (getScripts.py)

The block from `migrate_legacy_csv()` through `cleanup_legacy_files()` —
`migrate_legacy_csv`, `offer_noconfig_recovery`, `offer_storage_driver_mute`,
`offer_security_hardening`, legacy cleanup — moves behind `install_packages()`
and in front of the shell-setup completion. Relative order inside the block
is unchanged. Everything the block runs needs something `install_packages()`
delivers: PyYAML for the migration and the validators, `python3-dotenv` for
the hardening audit, `mc` for the hints the offers print.

New step right after `update_repository()`: `offer_bootstrap()` (component 5).
It must precede the Fish setup because `bootstrap.sh` installs the base
packages and generates the UTF-8 locale.

A source-inspection test (the repository has this pattern) asserts that in
`main()` the call to `install_packages(` precedes `offer_security_hardening(`
and `migrate_legacy_csv(`, and that `offer_bootstrap(` precedes
`install_fish_if_needed(`.

### 4. First-run dialogue: SSH access block (getScripts.py)

`run_first_time_setup()` gains a third block after proxy and DNS:

```
============================================================
SSH-Zugang für die Härtung
============================================================

Die Firewall lässt SSH später nur von diesen Adressen auf diesem Port zu.
Der Port wird hier nur festgelegt, nicht geändert.

Admin-Adressen und Port jetzt festlegen? (J/n): j
SSH-Port [22]: 2222
Admin-IPs, kommagetrennt [<current session address>]: 192.0.2.10, 198.51.100.7
.env angelegt: /root/.config/myodoo-docker/.env (nur für root lesbar)
sshd lauscht derzeit auf 22. Die Härtung wartet mit UFW und SSH, bis sshd auf 2222 lauscht – die sechs Schritte zeigt ups dann an.
```

Rules:

- **Port**: default is the first port of `_ssh_listen_ports()`, else 22;
  validated 1–65535; a port other than the live one is accepted and
  announced with the one-line note above (the hardening's lockout gate
  already refuses UFW/SSH until sshd listens there; `PORT_CHANGE_STEPS`
  remain the instructions). The script never changes the port — decision 4
  of the 28.09.2026 design stands.
- **Addresses**: comma- or space-separated; each must satisfy
  `ipaddress.ip_address()`. A network (`/24`) is rejected with the existing
  wording ("ALLOWED_IP erlaubt nur einzelne Adressen"); the offending entry
  is named and the whole line asked again, three attempts. Default is the
  list from `_ssh_peers()` (every established session, not only this one).
  An empty answer with no default ends the block with
  "Ohne Admin-IP keine .env – UFW würde SSH für niemanden öffnen" and the
  later hint.
- **"n" or Ctrl-C**: the block ends with the later hint; the existing
  derived-values offer in `offer_security_hardening()` stays the fallback,
  unchanged.
- **Writing**: `_write_env()` as today (0600, never overwrites). When
  `~/myodoo-docker/scripts/.env.example` exists (bootstrap path,
  `--reconfigure`), `_render_env()` renders it. When it does not — the
  README path runs the first-run dialogue before the clone — a minimal file
  is written: a header naming the template path for every other key, then
  `SSH_PORT=` and `ALLOWED_IP_<n>=` lines. Both forms carry only these keys
  active, for the same reason `_render_env()` comments everything else out.
- **An existing `.env`** (`--reconfigure` on a configured server): the block
  prints the current `SSH_PORT` and `ALLOWED_IP_<n>` values and the edit
  command, asks nothing, writes nothing.
- **Existing servers** already carry the first-run marker and never see the
  block; nothing changes for them.
- Comments (`ALLOWED_IP_<n>_COMMENT`) are not asked for. *My call*: the
  block has to stay short; the file is documented and editable.

### 5. Fresh-server offer: `offer_bootstrap()` (getScripts.py)

- **Trigger**: `shutil.which("docker")` is None, and
  `<repo>/scripts/bootstrap.sh` exists. Docker missing is the definition of
  "fresh" in this design; nginx or certbot missing alone is a configured
  host with a gap, which the readiness report already names.
- **Without a TTY** (stdin or stdout not a terminal): one status line —
  "Frischer Server ohne Docker – Grundausstattung einrichten mit:
  bash <repo>/scripts/bootstrap.sh" — and nothing else.
- **With a TTY**: a short list of what bootstrap installs (Docker CE with
  overlay2, nginx, certbot, UFW installed but off, fail2ban, unattended
  upgrades, python3-yaml/python3-dotenv, curl/git, UTF-8 locale), then
  `Grundausstattung jetzt einrichten? (J/n)`. Default yes.
- **Run**: `bash <repo>/scripts/bootstrap.sh` via `run_command(…,
  interactive=True)` with `env={"RUN_GETSCRIPTS": "0"}`. `RUN_GETSCRIPTS=0`
  is the recursion guard: bootstrap's own last step is to clone and run
  `getScripts.py`, and with the flag off its `clone_repo_and_run_getscripts()`
  returns before cloning — which also makes bootstrap's target-user
  resolution irrelevant for this call. No timeout: a Docker install behind a
  slow proxy takes minutes, and the output is streamed, so the operator
  sees progress. The proxy variables reach bootstrap through `os.environ`,
  which `ensure_proxy_environment()` restored at the start of the run.
- **Outcome**: `record_install("bootstrap", "installed", "Docker, nginx,
  certbot, UFW, fail2ban …")` on exit 0, `record_install("bootstrap",
  "failed", "exit <code> – see output above")` otherwise; the run continues
  either way (Fish and the scripts are still worth installing).
- **Declined**: `record_install("bootstrap", "skipped", "bash <path>")` so
  the install report carries the command, and the later hint is printed.
- After an accepted bootstrap the rest of the run sees Docker, the Python
  packages and the locale, so the readiness report at the end is the real
  one. The hardening offer (now after `install_packages()`) finds the `.env`
  from the first-run block and a working audit: on a fresh server that is
  the moment UFW, SSH and fail2ban get applied, behind the existing lockout
  gate.

### 6. Fresh-server awareness in the delivered scripts

- `ownerp_migrate.py --quiet` (no CSV, no YAML): when `shutil.which("docker")`
  is None the second line reads "Docker ist nicht installiert – zuerst
  bootstrap.sh (siehe ups), dann wizup" instead of recommending
  `--from-docker`. Version bump.
- `offer_noconfig_recovery()` returns before asking when Docker is absent:
  its option 1 is `--from-docker`.
- `server-readiness.py`: `backup_config` and `backup_recency` SKIP with
  "docker not installed", exactly as `update_config` already does. The
  maintenance-cron and logrotate FAILs stay — they are true and their fix
  (`setup-maintenance-cron.sh`) works without Docker. Version bump.

### 7. Noise (getScripts.py)

- `get_bat_version()`: a missing binary is `logger.debug`, not `logger.error`;
  `check_bat_version()` reports "bat is not installed" at INFO.
- The 7-Zip probe logs "7zz not found" once at INFO; the two repeats come
  from calling the probe three times in one run and are collapsed by
  remembering the result for the run.
- "Installed bat X is older than latest Y. Consider manual update from
  source" is INFO on Debian/Ubuntu: apt is the delivery path and nobody
  builds bat from source on a customer server.

### 8. Documentation

- `README.md`: both one-liners end in `exec fish` instead of
  `source ~/.config/fish/config.fish`; the fresh-server section says that
  `getScripts.py` offers `bootstrap.sh` when Docker is missing.
- `docs/usage/01-provisioning.md`: the "Danach neue Shell öffnen" hint names
  `exec fish` for a bash session; the getScripts section documents the
  first-run dialogue's third block and the bootstrap offer, both languages.
- `docs/INSTALLATION_GUIDE.md`: step 1/step 2 note that either order works
  now — bootstrap runs getScripts, getScripts offers bootstrap.
- `docs/COMPONENTS.md`, `usage/AGENT.md`, `RELEASE_NOTES.md`: versions and
  the new behaviour. `usage/AGENT.md` gets the non-TTY behaviour of the
  bootstrap offer (agents never see the prompt).
- The memory/skill note that `fish --version` is localised belongs in the
  code comment next to `probe_output()`, not in a document.

### Versions

| File | Today | New |
|---|---|---|
| `getScripts.py` | 9.33.0 | 9.34.0 |
| `scripts/ownerp_migrate.py` | 1.5.0 | 1.5.1 |
| `scripts/server-readiness.py` | 1.14.2 | 1.15.0 |
| `scripts/bootstrap.sh` | 1.15.3 | unchanged |

Dates from the environment: 27.10.2026.

## Settled details (from the builder check)

- **One home directory.** `setup_environment()` resolves the install home
  (SUDO_USER unless the operator came through `sudo su`/`-s`/`-i`, see its
  comment). That resolution moves into `resolve_install_home()`, which
  `setup_environment()`, the first-run dialogue (today
  `os.path.expanduser("~")`), the markers and the SSH block all use. The
  `.env` is `<home>/.config/myodoo-docker/.env` (`HARDENING_ENV_RELATIVE`),
  the template `<home>/myodoo-docker/scripts/.env.example`, bootstrap
  `<myodoo_docker>/scripts/bootstrap.sh` with `main()`'s `myodoo_docker`.
- **No re-exec after bootstrap.** Everything that needs what bootstrap
  installed runs in a subprocess with the system interpreter (the delivered
  scripts, `apt`, `docker`), the binaries land in `/usr/bin`, and our own
  probes set `LC_ALL=C`. `requests` is the one import this process needs
  and it is checked before anything runs; the README one-liner therefore
  installs `git python3-requests` together. The existing abort message
  stays.
- **The first-run marker is written when the dialogue ends**, whatever the
  SSH block did. Another go: `--reconfigure` re-runs all three blocks and
  the SSH block asks again when no `.env` exists; and the derived-values
  offer in `offer_security_hardening()` fires on the next interactive `ups`
  without a `.env`. Nothing more is needed.
- **`sudo` stripping covers the bare word only.** The script has no
  `sudo -u`/`-E` forms (`sudo -n true` is a direct `subprocess.run` in
  `is_root_or_has_sudo()`, untouched). No `run_command()` string embeds
  operator input before the `sudo` word; the regex is applied to the whole
  command string, and a test pins the four shapes.
- **`run_command()` already has `env=`** merged over a copy of `os.environ`
  (never a replacement) — the proxy survives.
- **`upgrade_pip()` stays where it is.** With the stripping it works as root
  without `sudo`; it needs nothing bootstrap installs.
- **TTY paths are covered by mocked tests**; the container exercises the
  non-TTY form and the Fish/sudo fixes; the accepted-bootstrap path is
  verified once on the demo server by the operator.

## Consequence for existing servers

None of the new prompts fire on a configured server: the first-run marker
exists, Docker exists, the `.env` exists or the derived-values offer still
handles it. The order change in `main()` moves four offers later in the run
by the duration of `install_packages()`; their output is the same. The
`sudo` stripping is a no-op for `ups` (which already runs via sudo as root)
except that it now also works where `sudo` is absent.

## Testing

Unit tests, stdlib `unittest`, next to the existing `tests/test_getscripts_*`:

- `fish, Version 4.9.3` and `fish, version 4.9.3` both parse; the probe
  helper passes `LC_ALL=C` (assert on the `env` argument of the mocked
  `subprocess.run`).
- `run_command()` sudo stripping as root and as a normal user (patch
  `os.geteuid`).
- First-run SSH block: port default and validation; address list parsing
  with commas, spaces, IPv6, a rejected `/24`; three failed attempts end the
  block; "n" writes nothing; template present → `_render_env()` output;
  template absent → minimal file with exactly the active keys; existing
  `.env` → nothing written.
- `offer_bootstrap()`: Docker present → silent; Docker absent without TTY →
  one status line, no `run_command`; Docker absent with TTY and "j" →
  `run_command` called with the script path and `RUN_GETSCRIPTS=0`; "n" →
  skipped entry in the install report.
- `main()` order by source inspection (component 3).
- `ownerp_migrate.py` no-config wording with and without Docker;
  `server-readiness.py` backup checks SKIP without Docker.

Live test: the Debian 13 Apple Container `gs-trixie` (fresh `debian:13`,
`sudo` absent, German `LANG`, the repository bind-mounted). Expected after
the change: Fish recognised, no `sudo` errors, the bootstrap offer printed
(non-TTY form in the container). `bootstrap.sh` itself cannot complete
there — Docker needs systemd — so the accepted-bootstrap path is verified on
the demo server, where the run that triggered this design is repeated.

## Out of scope

- Changing the SSH port from any script. Decision 4 of the 28.09.2026
  design.
- The derived-values offer in `offer_security_hardening()` for servers that
  predate this design: unchanged, because there the values come from real
  UFW rules, not from a guess.
- Allowing networks in `ALLOWED_IP_<n>`: a `server_hardening.py` change
  with its own UFW semantics; separate design if wanted.
- `bootstrap.sh` itself: no change. It already has `RUN_GETSCRIPTS` and is
  idempotent, which is what makes the offer possible.
