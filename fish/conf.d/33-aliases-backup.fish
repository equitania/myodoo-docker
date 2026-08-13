# Backup and Update Aliases
# Version 2.0.0 | 13.08.2026

# Backup operations
alias dobk='$HOME/container2backup.py'
alias edbk='mcedit $HOME/container2backup.yaml'
alias llbk='ll /opt/backups/docker'
alias cpbk='cp /opt/backups/docker/'
alias cdbk='cd /opt/backups/docker'

# Update operations
# NOTE: `doup` is a function (functions/linux/doup.fish), not an alias.
alias edup='mcedit $HOME/docker2update.yaml'
alias doval='$HOME/ownerp_validate.py'
# The only tool here that writes to the configuration - it validates first,
# refuses without a terminal, and never removes an entry. Bare `wiz` asks
# which file; the flags go straight there.
alias wiz='$HOME/ownerp_wizard.py'
alias wizup='$HOME/ownerp_wizard.py --update'
alias wizbk='$HOME/ownerp_wizard.py --backup'

# Maintenance cron: what runs when, and when it last ran. Bare `docron` only
# reports; editing goes through `konsole` or --set/--enable/--disable.
alias docron='$HOME/ownerp_cron.py'

# The whole server on one page: instances, backup ages, maintenance jobs and
# the readiness checks. Reads only. Exit code 0 clean / 1 attention / 2 broken,
# so it is usable from cron without parsing the text.
alias dostat='$HOME/ownerp_state.py'

# The same facts, plus editing, in a full-screen interface. Starts nothing:
# no updates, no backups, no container operations - `doup` and `dobk` stay
# what they are. Needs Textual; without it, it names dostat/wiz/docron/doval
# and stops, so nothing here is ever the only route to anything.
alias konsole='$HOME/ownerp_console.py'
