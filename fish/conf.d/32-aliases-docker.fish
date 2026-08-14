# Docker Aliases
# Version 1.3.0 | 14.08.2026

# Docker base
alias dk='docker'

# Container listing
#
# dps and dpsall are functions now (functions/dps.fish, functions/dpsall.fish),
# not aliases. They used to pipe `docker ps --format table` into `sort`, which
# sorted the header line along with the containers — under a UTF-8 locale
# "NAMES" collates after "ivy-odoo", so the column titles ended up at the
# bottom of every listing. An alias defined here would shadow the function, so
# nothing may reintroduce one under either name.
alias dkpsf='docker inspect -f "{{.Name}} {{.Config.Cmd}}" (docker ps -a -q)'

# Image management
#
# dpi is a function too (functions/dpi.fish): `docker images` on Docker 29 lists
# DISK USAGE, CONTENT SIZE and EXTRA and no age at all. An alias here would
# shadow the function — nothing may reintroduce one under that name either.

# Volume management
alias dkvol='$HOME/myodoo-docker/scripts/check_docker_volumes.sh'

# Stop all containers
alias dkstop='docker stop (docker ps -a -q)'

# Prune commands (use with caution!)
# dkprs/dkprv/dkprf/dkprfa run WITHOUT -f → Docker prompts [y/N] before deleting.
# dkprfa also wipes unused *volumes* (--volumes) — confirm carefully.
# dkprfs uses -f (no prompt) but never touches volumes (no --volumes).
alias dkprs='docker system prune'
alias dkprv='docker volume prune'
alias dkprf='docker system prune -a'
alias dkprfa='docker system prune -a --volumes'
alias dkprfs='docker system prune -f'

# ctop Docker TUI
alias ct='ctop'

# Docker exec shortcuts
alias exec-live='docker exec -ti live-odoo env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l'
alias exec-test='docker exec -ti test-odoo env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l'

# Docker Compose shortcuts
alias dco='docker compose'
alias dcup='docker compose up -d'
alias dcdown='docker compose down'
alias dclogs='docker compose logs -f'
alias dcps='docker compose ps'
