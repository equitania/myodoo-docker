# Security hardening checked on every `ups` — Design

*28.09.2026 · status: specified, not yet implemented*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

---

## Why this exists

A fresh Debian 13 VPS on an OpenStack cloud was provisioned on 28.09.2026 by
the book: `bootstrap.sh`, `getScripts.py`, `setup-maintenance-cron.sh`. Every
one of them succeeded, and the server was still wide open:

- **UFW was installed and inactive.** `bootstrap.sh` leaves it off on purpose —
  switching it on before the SSH port and the admin IPs are known locks the
  operator out. Hardening is a separate step, `server_hardening.py --apply`,
  and nothing on the host ever mentions it again after the bootstrap's closing
  message scrolls away.
- **fail2ban ran the bootstrap's baseline `sshd` jail only**, no nginx jails,
  no `recidive`, banning through nftables rather than UFW.
- **There was no `.env`**, so the hardening script could not have run even if
  someone had remembered it.
- **Port 22 was reachable from the internet** although the operator believed
  the provider's security group restricted it: 253 failed logins in six hours,
  49 bans by the baseline jail. The operator's belief was wrong; the log was
  not.

`chk` reported none of this, because none of it is among its checks. The
readiness report — the block every `ups` prints, `chk`, `dostat`/`konsole` and
the Monday cron mail — is the one place an operator reliably looks, and
security was not in it.

Walking the hardening through module by module in that session also surfaced
eight defects in the first-setup path. They are fixed here too, because
several of them sit directly on the path this design puts in front of every
operator.

## Decisions

Taken in the conversation, with the alternatives that were rejected:

1. **`ups` reports and offers; it never hardens on its own.** On a terminal it
   asks once per run: fix now / show the commands / later / mute. Without a
   terminal (cron, CI, a piped `ups`) it only reports. *Rejected:* report only
   (operators already skip the closing hint of `bootstrap.sh`); automatic apply
   (UFW and SSH can lock an operator out of a customer server).
2. **UFW, SSH and the Docker restart are applied only after a lockout
   pre-check passes** (see *Lockout gate*). When it does not pass, `ups` prints
   the commands and the reason instead. *Rejected:* never applying them from
   `ups` (leaves the most important module to the step people skip); treating
   them like the harmless modules.
3. **The check lives in the readiness report** and calls the hardening
   script's own audit. *Rejected:* `ups` printing the audit directly (no mute,
   no Monday mail, long output, a second path beside `chk`); reimplementing the
   checks in `server-readiness.py` (two implementations drift — the reason
   `ownerp_state.py` runs `run_checks()` instead of its own).
4. **`ups` never changes the SSH port.** A port change needs the provider's
   firewall opened first, which no script on the host can see or verify. When
   `SSH_PORT` differs from the port sshd listens on, `ups` shows the ordered
   manual sequence and stops there.

## Components

### 1. `server_hardening.py` (1.8.0 → 1.9.0)

**`--json` audit mode.** Runs the audit exactly as today, without `--apply`,
and prints one JSON document on stdout instead of the coloured text:

```json
{
  "version": "1.9.0",
  "env": {"path": "/root/.config/myodoo-docker/.env", "present": true,
          "ssh_port": 16667, "allowed_ips": 4},
  "modules": {
    "ufw":      {"ok": 3, "warn": 0, "fail": 1,
                 "findings": [{"level": "fail", "text": "UFW ist NICHT aktiv"}]},
    "fail2ban": {"ok": 8, "warn": 0, "fail": 0, "findings": []}
  },
  "error": null
}
```

Implementation: `header()` records the current module, `ok()`/`warn()`/`fail()`
append to a per-module collector in addition to printing; in `--json` mode
printing is suppressed and the collector is dumped at the end. No audit
function changes its logic. A configuration error (`validate_config()`)
produces `"error": "<text>"` and exit 1, never a traceback.

**`--json` never writes.** Today `main()` creates
`/root/.config/myodoo-docker/` and copies `.env.example` into it even in audit
mode. That seeding moves behind `--apply` (and the `.env` offer in
`getScripts.py`); the readiness check must be free of side effects like every
other check.

**No admin IPs in `--json` output.** Findings that name an allowlist IP carry
its `ALLOWED_IP_<n>_COMMENT` instead, or `ALLOWED_IP_<n>` when there is no
comment. The text-mode summary line becomes
`Allowlist: 4 IP(s) aus .env erkannt (Office A, Office B, …)` — count plus
comments. Per-rule text lines keep the IP, because an operator at the console
needs it to act. *(first-setup defect 4)*

**Canonical module order.** `--module ssh ufw` currently runs SSH first — the
modules run in the order typed. They now always run in the order of the
`modules` dict (`ufw` before `fail2ban` before `ssh`), whatever the order on
the command line.

**UFW: rules first, then enable.** `audit_ufw()` enables UFW before it adds
any allow rule, so for a few seconds new SSH connections are refused. The
apply path now sets defaults and adds all public and restricted rules first,
and runs `ufw enable` last. *(first-setup defect 6)*

**Package installs get a real timeout.** Every `apt-get install` goes through
`run()` with its 30 s default; AIDE timed out on the fresh VPS and finished in
the background. Installs now run with `timeout=600` and
`DEBIAN_FRONTEND=noninteractive` (AIDE pulls in a mail transport agent whose
debconf prompt nobody would see). *(first-setup defect 5)*

**SSH comparison normalises whitespace.** Debian writes
`Subsystem sftp     /usr/lib/openssh/sftp-server`; the audit compared it
literally and reported a permanent false `✗`. Values are compared after
collapsing runs of whitespace. *(first-setup defect 7)*

**`.env.example` lookup** falls back to `~/myodoo-docker/scripts/.env.example`
when the script runs from a directory without one (see delivery below).

### 2. `getScripts.py`: delivery (9.25.0 → 9.26.0)

`copy_scripts()` adds `server_hardening.py` and `hardening_config.yaml`, so
`/root/server_hardening.py` — the path the documentation has always named —
exists. The YAML is overwritten on every `ups` like every delivered file;
host-specific values belong in `.env`, never in the YAML, and the delivered
header of `hardening_config.yaml` says so. *(first-setup defect 1)*

### 3. `server-readiness.py`: security checks (1.10.0 → 1.11.0)

One audit run per report, shared by several checks. `run_checks()` calls
`python3 <home>/server_hardening.py --json` once (subprocess, timeout 120 s)
and caches the parsed result on the context; the readiness script keeps
running without PyYAML, as it does today.

Several check ids instead of one, so that a host which deviates on purpose
mutes only that part — a customer server behind a corporate firewall mutes
`hardening_firewall` and keeps everything else:

| check id | hardening modules | severity when the module reports `fail` |
|---|---|---|
| `hardening_env` | — (`.env` present, `SSH_PORT` set, ≥ 1 `ALLOWED_IP_<n>`) | FAIL |
| `hardening_firewall` | `ufw` | FAIL |
| `hardening_fail2ban` | `fail2ban` | FAIL |
| `hardening_ssh` | `ssh` | FAIL |
| `hardening_kernel` | `sysctl`, `sysctl_persist`, `kernel_modules` | WARN |
| `hardening_docker` | `docker` | WARN |
| `hardening_updates` | `auto_updates` | WARN |
| `hardening_integrity` | `auditd`, `aide` | WARN |
| `root_login_locked` | — (see below) | WARN |

A module with only `warn` findings yields WARN. `nginx` and `ports` stay out of
the verdict: nginx is covered by `deploy-nginx-base.sh` and the existing nginx
checks, and the ports module is advisory by its own description.

Every non-OK finding carries one copy-paste fix, as all readiness findings do:
`python3 /root/server_hardening.py --apply -m <modules>`. `hardening_env`
points at `ups` (which offers to create the file) and at the manual
`cp`/`mcedit` alternative.

**SKIP, never a false alarm**, when: `server_hardening.py` is missing (a host
one `ups` behind), the subprocess fails or times out, the JSON does not parse.
The SKIP detail names the reason.

**`root_login_locked`** *(first-setup defect 8)*: cloud images lock root's
password and set `disable_root: true` in `/etc/cloud/cloud.cfg`. WARN when
`passwd -S root` reports `L` **and** `hardening_config.yaml` expects
`PermitRootLogin yes`. Fix: `passwd root` and a drop-in
`/etc/cloud/cloud.cfg.d/99-ownerp-root.cfg` with `disable_root: false`. Nothing
applies this automatically — it needs a password.

**Backup/update config on a host without Odoo** *(first-setup defect 2)*: when
no container exists at all, `check_backup_config` and `check_update_config`
point at `wiz` (add the first instance) instead of
`ownerp_migrate.py --from-docker`, which has nothing to rebuild from there.

### 4. `getScripts.py`: `offer_security_hardening()`

Runs after `offer_storage_driver_mute()`, before `print_readiness_report()`, so
the report shows the state after whatever the operator chose.

Silent unless **all** hold, like the two existing offers: stdin and stdout are
a TTY; `~/server_hardening.py` exists; its `--json` audit ran; at least one
`hardening_*` check id is non-OK and not muted. Any failure in the gate is
"skip", never a broken `ups`.

**Step 1 — `.env` missing.** Offer to create it. Suggested values, each
confirmed or overwritten at the prompt: `SSH_PORT` = the port sshd listens on
now (`sshd -T`), `ALLOWED_IP_1` = the source address of the current SSH
session(s), further IPs optional. Written from `.env.example` via temp file and
`os.replace()`, mode 0600, directory 0700. An existing `.env` is never touched.
*(first-setup defect 3)*

**Step 2 — the offer.** One screen listing the non-OK areas, then:
`[b]` fix now · `[z]` show the commands · `[s]` later · `[m]` mute one area
(`ownerp_mute.py <check_id> --reason "…"`).

**Fix now** applies in two groups:

- *Harmless:* `sysctl sysctl_persist kernel_modules auto_updates auditd aide
  fail2ban` — `--apply -f` directly. AIDE's database is initialised last, after
  every other change, so it does not immediately report them.
- *Guarded:* `ufw`, `ssh`, `docker` — only through the lockout gate.

#### Lockout gate

Evaluated right before the guarded modules. **All** must hold, otherwise that
module is skipped, its command printed, and the failing condition named:

| condition | why |
|---|---|
| `.env` present, ≥ 1 `ALLOWED_IP_<n>` | an enabled UFW with no allowlist opens SSH to nobody |
| every established peer on sshd's port (`ss -tnH state established`) is in the allowlist | the session running `ups` — and any other admin's — must survive. `SSH_CONNECTION` is not used: `sudo` strips it |
| `SSH_PORT` equals the port sshd listens on | otherwise this is a port change — decision 4, never from `ups` |
| `ssh.socket` is not active | with socket activation `Port` in `sshd_config` has no effect; the firewall would move and sshd would not |
| **docker only:** `docker ps -q` is empty | the daemon restart needed for `daemon.json` stops every container. With containers running, `daemon.json` is written and the restart is printed as a maintenance-window step |

On a port mismatch the printed sequence is the one proven on 28.09.2026:
open the new port in the provider firewall → `SSH_PORT` in `.env` →
`--apply -m ufw fail2ban ssh` → log in on the new port from a second terminal
→ delete the old UFW rules → close the old port at the provider.

## Consequence for existing servers

After the first `ups` with this version, every server where hardening was
never applied shows new FAILs — in the block after `ups`, in `chk`, and in the
Monday mail. That is the intent. A server that deviates on purpose mutes the
area with a reason, once. The release notes say so explicitly.

## Documentation

- `usage/AGENT.md`: `/root/server_hardening.py` now true; new `--json` flag;
  the new check ids; `ups` offers hardening.
- `docs/usage/01-provisioning.md`: step 3 rewritten around the `ups` offer; the
  manual path stays as the alternative; the port-change sequence; the
  cloud-image root lock.
- `docs/usage/09-reference.md`, `docs/COMPONENTS.md`: versions and features.
- `RELEASE_NOTES.md`: one entry per changed script.
- `bootstrap.sh` closing message: points at `ups` / `chk` instead of the repo path.

No IP addresses, hostnames or customer names in any of it — placeholders only
(`192.0.2.x`, "Office A").

## Testing

`uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests`

- `tests/test_server_hardening.py` *(new)*: collector counts per module;
  `--json` shape; no IP in `--json` output; `--json` creates no directory or
  file (temp `HOME`/root); canonical module order; UFW apply issues `enable`
  after the last `allow` (recorded `run()` calls); whitespace-normalised SSH
  comparison; install calls carry the long timeout and `DEBIAN_FRONTEND`.
- `tests/test_server_readiness.py`: mapping from module result to each check
  id and severity; SKIP on missing script, non-zero exit, timeout, bad JSON;
  mute applies per check id; `root_login_locked`; the `wiz` hint without
  containers.
- `tests/test_getscripts_security_offer.py` *(new)*: silent without a TTY;
  silent when all OK or all muted; `.env` creation (values, mode 0600, never
  overwrites); each lockout-gate condition blocks exactly its module; docker
  restart only with no containers; port mismatch prints the sequence and
  applies nothing guarded.
- `tests/test_delivered_scripts.py`: version header and `SCRIPT_VERSION` agree
  for the three bumped scripts; `server_hardening.py` and
  `hardening_config.yaml` are in the delivery list.

No test touches a real firewall, sshd or package manager: `run()`, `ss`,
`sshd -T`, `passwd -S` and `docker` are replaced by recorded fakes.

## Out of scope

- Changing the SSH port from `ups` (decision 4).
- nginx hardening beyond what `deploy-nginx-base.sh` already deploys.
- Checking the provider's firewall or security group — invisible from the host.
- A fish alias for the hardening script; the full path is what the fix lines print.
