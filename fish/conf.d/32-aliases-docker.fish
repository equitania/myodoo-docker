# Docker Aliases
# Version 1.1.0 | 14.07.2026

# Docker base
alias dk='docker'

# Container listing
alias dps='docker ps -a --format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" | sort'
alias dpsall='docker ps -a --format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Command}}\t{{.CreatedAt}}\t{{.Status}}\t{{.Ports}}" | sort'
alias dkpsf='docker inspect -f "{{.Name}} {{.Config.Cmd}}" (docker ps -a -q)'

# Image management
alias dpi='docker images'

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
