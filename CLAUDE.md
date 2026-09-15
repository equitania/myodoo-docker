# CLAUDE.md

Guidance for Claude Code in this repository. The general rules — German replies and
greeting, commit prefixes, version headers, DD.MM.YYYY dates from the environment,
UTF-8 and German typography, container safety, data protection in Git hosting — live
in `~/.claude/*.md` and are not repeated here.

## Push: always both remotes

```bash
git push origin <branch>      # GitLab: gitlab.ownerp.io
git push upstream <branch>    # GitHub: github.com/equitania/myodoo-docker — PUBLIC
```

`git branch --show-current` is authoritative (currently `2026`); a branch name written
into documentation goes stale.

**`upstream` is public.** No customer names, hostnames, internal zones, IP addresses,
customer domains or e-mails in code, tests, comments, docs or release notes. Scan the
staged diff before every commit. Customer reports and customer YAMLs stay outside the
repo.

## What this repo is

Server toolkit for ownERP/Odoo hosts (Debian/Ubuntu, Docker, nginx native under
systemd — never in a container). `getScripts.py` installs it into `/root`, `ups`
updates it. On customer servers operators work as root via `sudo su`, and their shell
is **fish**: every command an operator is meant to type must be fish syntax.

Where to look instead of guessing:

- `docs/COMPONENTS.md` — every script with version and features; read before changing one
- `docs/usage/09-reference.md` — all scripts, flags, fish aliases and functions
- `usage/AGENT.md` — capability card; update it whenever a flag or command changes
- `scripts/container2backup.yaml`, `scripts/docker2update.yaml` — the commented config templates
- `RELEASE_NOTES.md` — one entry per change, newest first, in the existing English style

Layout: `getScripts.py`, `scripts/` (tools delivered to servers), `fish/` (server
aliases and functions), `Dockerfiles/v16-odoo|v18-odoo|v19-odoo/` (build context incl.
`bin/boot`), `tests/`, `docs/`.

## Server commands that cannot be guessed

| Command | Script | Notes |
|---|---|---|
| `ups` | `getScripts.py` | fish function; runs the script via sudo with the proxy preserved; restarts itself once when the pull brings a newer version |
| `doup` | `scripts/update_docker_odoo.py` | `-s NAME`, `--type M\|F\|N`, `--comment`, `--no-cache`, `--validate` |
| `dobk` | `scripts/container2backup.py` | `--sql-only`, `--validate` — there is no `--dry-run` |
| `doval` | `ownerp_validate.py` | read-only; exit 0 clean, 1 errors, 2 unreadable |
| `wiz` / `wizup` / `wizbk` | `ownerp_wizard.py` | the only tool that writes a customer YAML |
| `docron` | `ownerp_cron.py` | bare on a terminal: menu; scripts and agents use flags or `--no-input`; `--disable container2backup` switches both backup lines |
| `dostat` / `konsole` | `ownerp_state.py` / `ownerp_console.py` | the whole server; `konsole` starts nothing |
| `chk` | `server-readiness.py` | read-only; true-but-irrelevant findings are muted via `ownerp_mute.py` |

## Config pitfall

`container2backup.yaml` has `defaults`, `services` and `databases`. There is no
`odoo_instances`, no `backup_folder` and no `db_pass` — encryption credentials come
from a `.env` file. Read the template before writing a parser or an example.

## Development

- Delivered scripts run on system Python 3 with `python3-yaml` only — no new
  dependencies. Their `# Version:` header and `SCRIPT_VERSION`/`SCRIPT_DATE` must agree;
  `tests/test_delivered_scripts.py` enforces it.
- Tests: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests`.
  A plain `python3 -m unittest` silently skips the Textual tests.
- Servers carry destructive shortcuts: the functions `dkrm`, `dkrmi`, `dkrmv` and the
  prune aliases `dkprs`, `dkprv`, `dkprf`, `dkprfa`, `dkprfs`. Never hand one to an
  operator; name specific, verified resources instead.
