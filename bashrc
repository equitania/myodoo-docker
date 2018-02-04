# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples

# You may uncomment the following lines if you want `ls' to be colorized:
export LS_OPTIONS='--color=auto'
eval "`dircolors`"
alias ls='ls $LS_OPTIONS'
alias ll='ls $LS_OPTIONS -lh'
alias la='ls $LS_OPTIONS -la'

# Some more alias to avoid making mistakes:
alias rm='rm -i'
alias cp='cp'
alias mv='mv -i'

# Shortcuts
alias cdngx='cd /etc/nginx/conf.d/'
alias ngx+='/etc/init.d/nginx start'
alias ngx-='/etc/init.d/nginx stop'
alias ngx#='/etc/init.d/nginx restart'
alias ngxr='/etc/init.d/nginx reload'
alias dps='docker ps -a'
alias dpi='docker images'
alias syspatch='apt-get update && apt-get dist-upgrade && apt-get autoremove'
alias dobk='/root/backup_odoo_docker_postgres_on_host.py'
alias doup='/root/update_docker_myodoo.py'
alias edbk='nano docker2backup.csv'
alias edup='nano docker2update.csv'
alias pga='sudo -u postgres pg_activity -U postgres'


export EDITOR=nano
