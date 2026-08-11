# Backup and Update Aliases
# Version 1.1.0 | 11.08.2026

# Backup operations
alias dobk='$HOME/container2backup.py'
alias edbk='mcedit $HOME/container2backup.yaml'
alias llbk='ll /opt/backups/docker'
alias cpbk='cp /opt/backups/docker/'
alias cdbk='cd /opt/backups/docker'

# Update operations
# NOTE: `doup` is a function (functions/linux/doup.fish), not an alias - it
# picks between the TUI and the runner. An alias here would shadow it.
alias tui='$HOME/ownerp_tui.py'
alias edup='mcedit $HOME/docker2update.yaml'
