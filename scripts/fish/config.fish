# Fish Shell configuration powered by ownerp.com
# Version 1.0.0
# Date 19.11.2025

################################
# BASIC CONFIGURATION
################################

# Path configuration
set -gx PATH $HOME/bin $HOME/.local/bin /usr/local/bin $PATH

# Initialize zoxide
if type -q zoxide
    zoxide init fish | source
end

################################
# ALIASES
################################

# Fish configuration
alias fishcfg='mcedit ~/.config/fish/config.fish'

# Default settings
alias ls='ls -h --color --classify'
alias ll='ls -alh --color --classify'
alias lg='lazygit'
alias grep='grep --color=auto'
alias nano='nano --nowrap -B -c'
alias hg='history | grep'
alias nf='neofetch'
alias ff='fastfetch'
alias mce='mcedit'
alias bat='batcat'

# Safety aliases
alias rm='rm -I'
alias chmod='chmod -c'
alias chown='chown -c'
alias shred='shred -u -z'

# Nginx aliases
alias cdngx='cd /etc/nginx/conf.d/'
alias ngx+='sudo systemctl start nginx'
alias ngx-='sudo systemctl stop nginx'
alias ngx#='sudo systemctl restart nginx'
alias ngxr='sudo systemctl reload nginx'
alias ngxs='sudo systemctl status nginx'
alias ngx!='sudo nginx -t'
alias ngxl='sudo nginx -t -c /etc/nginx/nginx.conf'
alias ngxset="nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/"
alias showcerts='certbot certificates'

# System aliases
alias prepatch='sudo screen -S sysupdate'
alias cleandlog='sudo cat /dev/null > /var/lib/docker/containers/*/*-json.log'
alias syspatch='sudo journalctl --vacuum-time=7d && sudo journalctl --vacuum-size=2G && sudo apt -y update && sudo apt -y dist-upgrade && sudo apt -y autoremove && sudo apt -y autoclean && docker system prune -f && docker volume prune'
alias dusort='du /var --max-depth=1 | sort -nr | cut -f2 | xargs -n 1 du -hs'
alias f2b='fail2ban-client status'
alias ups="sudo $HOME/getScripts.py && sudo cp $HOME/myodoo-docker/getScripts.py $HOME/ && source ~/.config/fish/config.fish"

# Claude CLI alias (if installed)
if test -f "$HOME/.claude/local/claude"
    alias claude="$HOME/.claude/local/claude"
end

# ownERP aliases
alias dobk="$HOME/container2backup.py"
alias doup="$HOME/update_docker_odoo.py"
alias doup2="$HOME/update_docker_myodoo.py"
alias edbk="mcedit $HOME/container2backup.yaml"
alias edbk2="mcedit $HOME/container2backup.csv"
alias edup="mcedit $HOME/docker2update.yaml"
alias edup2="mcedit $HOME/docker2update.csv"
alias llbk='ll /opt/backups/docker'
alias cpbk='cp /opt/backups/docker/'

# Docker aliases
alias dk='docker'
alias dps='docker ps -a --format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" | sort'
alias dpsall='docker ps -a --format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Command}}\t{{.CreatedAt}}\t{{.Status}}\t{{.Ports}}" | sort'
alias dpi='docker images'
alias dkpsf='docker inspect -f "{{.Name}} {{.Config.Cmd}}" (docker ps -a -q)'
alias dkvol="$HOME/myodoo-docker/scripts/check_docker_volumes.sh"
alias dkstop='docker stop (docker ps -a -q)'
alias dkrm='docker rm (docker ps -a -q)'
alias dkrmi='docker rmi (docker images -q)'
alias dkrmv='docker volume rm (docker volume ls -q)'
alias dkprs='docker system prune'
alias dkprv='docker volume prune'
alias dkprf='docker system prune -a'
alias dkprfa='docker system prune -a --volumes'
alias dkprfs='docker system prune -f'
alias ox='oxker'

# Docker exec aliases
alias exec-live='docker exec -ti live-odoo env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l'
alias exec-test='docker exec -ti test-odoo env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l'

################################
# STARTUP COMMANDS
################################

# Run fastfetch if available
if test -f /usr/bin/fastfetch
    fastfetch
end

# Start in home directory
cd $HOME
