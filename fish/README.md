# Fish Shell Configuration for ownERP Server Environment

Version 1.1.0 | 15.09.2026

## Overview / Übersicht

This directory contains the Fish shell configuration for ownERP Docker server environments.
Fish shell replaces ZSH with Oh-My-Zsh as the primary shell starting from version 7.0.0.

Dieses Verzeichnis enthält die Fish-Shell-Konfiguration für ownERP Docker Server-Umgebungen.
Fish Shell ersetzt ZSH mit Oh-My-Zsh als primäre Shell ab Version 7.0.0.

## Structure / Struktur

```
fish/
├── config.fish                    # Minimal entry point / Minimaler Einstiegspunkt
├── README.md                      # This documentation / Diese Dokumentation
├── conf.d/
│   ├── 00-env.fish               # Environment variables / Umgebungsvariablen
│   ├── 10-path.fish              # PATH configuration (cross-platform)
│   ├── 10-path.linux.fish        # PATH configuration (Linux-specific)
│   ├── 20-tools.fish             # Tool initialization (Zoxide, Starship)
│   ├── 30-aliases-system.fish    # System aliases (base)
│   ├── 30-aliases-system.linux.fish # System aliases (Linux)
│   ├── 31-aliases-git.fish       # Git aliases
│   ├── 32-aliases-docker.fish    # Docker aliases
│   ├── 33-aliases-backup.fish    # Backup & update aliases (dobk, edbk, llbk, doval, wiz, wizup, wizbk, docron, dostat, konsole, edup)
│   ├── 34-aliases-nginx.fish     # Nginx aliases (ngx+, ngx-, etc.)
│   ├── 35-aliases-odoo.fish      # Odoo aliases
│   ├── 40-completions.fish       # Dynamic completions
│   └── 50-prompt.fish            # Prompt & startup
└── functions/
    └── linux/
        ├── __ownerp_docker_ps.fish # Shared body behind dps and dpsall
        ├── chk.fish               # Server readiness report (read-only)
        ├── cleandlog.fish         # Truncate Docker container logs (--dry-run reports without writing)
        ├── dkrm.fish              # Docker remove containers (with confirmation)
        ├── dkrmi.fish             # Docker remove images (with confirmation)
        ├── dkrmv.fish             # Docker remove volumes (with confirmation)
        ├── doup.fish              # Update Odoo containers
        ├── dpi.fish               # Docker images as a table (repository:tag, ID, size, age)
        ├── dps.fish               # Docker containers as a table
        ├── dpsall.fish            # Docker containers as a table, with details
        ├── ownerp-help.fish       # Command overview, printed on login and via `help`
        ├── syspatch.fish          # System update function
        └── ups.fish               # Update ownERP scripts
```

## Key Aliases / Wichtige Aliase

### Docker
| Alias | Description / Beschreibung |
|-------|---------------------------|
| `dk` | Docker shortcut |
| `dps` | List containers as a table (name, image, status, ports) / Container als Tabelle |
| `dpsall` | The same with ID, command and creation time / Dasselbe mit ID, Kommando und Erstellzeit |
| `dpi` | List images |
| `dkstop` | Stop all containers |
| `dkrm` | Remove all containers (with confirmation) |
| `dkrmi` | Remove all images (with confirmation) |
| `dkrmv` | Remove all volumes (with confirmation) |

### Backup & Update
| Alias | Description / Beschreibung |
|-------|---------------------------|
| `dobk` | Run backup script |
| `edbk` | Edit backup configuration |
| `llbk` | List backups |
| `doup` | Run update script |
| `edup` | Edit update configuration |
| `doval` | Read-only validation of both YAML configs against their schema / rein lesende Prüfung beider YAML-Konfigurationen |
| `wiz` | Guided editing of `docker2update.yaml` — the only tool here that writes to the configuration / geführtes Bearbeiten von `docker2update.yaml` |
| `wizup` | `wiz` pre-selected for the update configuration / `wiz` mit vorausgewählter Update-Konfiguration |
| `wizbk` | `wiz` pre-selected for the backup configuration / `wiz` mit vorausgewählter Backup-Konfiguration |
| `docron` | Maintenance cron overview — when jobs run and when they last ran / Wartungs-Cron-Übersicht, wann Jobs laufen und zuletzt liefen |
| `dostat` | The whole server on one page: instances, backup ages, maintenance jobs, readiness (read-only) / der ganze Server auf einer Seite (rein lesend) |
| `konsole` | Full-screen console for the same facts plus editing; starts nothing itself / Vollbild-Konsole für dieselben Fakten plus Bearbeitung, startet selbst nichts |

### Nginx
| Alias | Description / Beschreibung |
|-------|---------------------------|
| `ngx+` | Start Nginx |
| `ngx-` | Stop Nginx |
| `ngx#` | Restart Nginx |
| `ngxr` | Reload Nginx |
| `ngxs` | Nginx status |
| `ngx!` | Test Nginx configuration |

### System (Linux)
| Alias | Description / Beschreibung |
|-------|---------------------------|
| `syspatch` | Full system update & cleanup |
| `ups` | Update ownERP scripts |
| `chk` | Server readiness report (read-only) / Readiness-Report (rein lesend) |
| `cleandlog` | Truncate Docker container logs (`--dry-run` reports without writing) / Container-Logs leeren |

## Installation / Installation

The Fish configuration is automatically installed by `getScripts.py`.
Manual installation:

Die Fish-Konfiguration wird automatisch von `getScripts.py` installiert.
Manuelle Installation:

```bash
# Copy configuration / Konfiguration kopieren
cp -r fish/* ~/.config/fish/

# Set Fish as default shell / Fish als Standard-Shell setzen
chsh -s /usr/bin/fish
```

## Customization / Anpassung

### Adding Custom Aliases / Eigene Aliase hinzufügen

Create a file in `~/.config/fish/conf.d/` with a name like `99-custom.fish`:

Erstellen Sie eine Datei in `~/.config/fish/conf.d/` mit einem Namen wie `99-custom.fish`:

```fish
# ~/.config/fish/conf.d/99-custom.fish
alias myalias='my-command'
```

### Adding Custom Functions / Eigene Funktionen hinzufügen

Create a file in `~/.config/fish/functions/`:

Erstellen Sie eine Datei in `~/.config/fish/functions/`:

```fish
# ~/.config/fish/functions/myfunction.fish
function myfunction --description "My custom function"
    echo "Hello from myfunction!"
end
```

## ZSH Fallback

A simplified `.zshrc` without Oh-My-Zsh is provided as fallback.
To use ZSH instead of Fish:

Eine vereinfachte `.zshrc` ohne Oh-My-Zsh wird als Fallback bereitgestellt.
Um ZSH statt Fish zu verwenden:

```bash
chsh -s /usr/bin/zsh
```

## Starship Prompt

The prompt is provided by [Starship](https://starship.rs/). Configuration is stored in
`~/.config/starship.toml`.

Der Prompt wird von [Starship](https://starship.rs/) bereitgestellt. Die Konfiguration
befindet sich in `~/.config/starship.toml`.

## Troubleshooting / Fehlerbehebung

### Fish not starting / Fish startet nicht

Check Fish installation:
```bash
fish --version
```

### Aliases not working / Aliase funktionieren nicht

Reload configuration:
```bash
source ~/.config/fish/config.fish
```

### Starship not showing / Starship wird nicht angezeigt

Check Starship installation:
```bash
starship --version
```

Reinitialize:
```fish
starship init fish | source
```
