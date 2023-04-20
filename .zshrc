#ZSH powered by ownerp.com
# Version 3.1.2
# Date 20.04.2023

# If you come from bash you might have to change your $PATH.
export PATH=$HOME/bin:/usr/local/bin:$HOME/.local/bin:/root/.local/bin:$HOME/compose-update/:$PATH

# Path to your oh-my-zsh installation.
export ZSH=$HOME/.oh-my-zsh

# Set name of the theme to load. Optionally, if you set this to "random"
# it'll load a random theme each time that oh-my-zsh is loaded.
# See https://github.com/robbyrussell/oh-my-zsh/wiki/Themes
#ZSH_THEME="robbyrussell"
#ZSH_THEME="gnzh"
#ZSH_THEME="juanghurtado"
#ZSH_THEME="bira"
#ZSH_THEME="muse"
ZSH_THEME="fino-time"
#ZSH_THEME="avit"

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following # --prefix=/etc/nginx
# --sbin-path=/usr/sbin/nginx
# --modules-path=/usr/lib/nginx/modules
# --conf-path=/etc/nginx/nginx.conf
# --error-log-path=/var/log/nginx/error.log
# --http-log-path=/var/log/nginx/access.log
# --pid-path=/var/run/nginx.pid
# --lock-path=/var/run/nginx.lock
# --http-client-body-temp-path=/var/cache/nginx/client_temp
# --http-proxy-temp-path=/var/cache/nginx/proxy_temp
# --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp
# --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp
# --http-scgi-temp-path=/var/cache/nginx/scgi_temp
# --user=nginx
# --group=nginx
# --with-http_ssl_module
# --with-http_v2_moduleline to use hyphen-insensitive completion. Case
# sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to change how often to auto-update (in days).
export UPDATE_ZSH_DAYS=90

# Uncomment the following line to enable command auto-correction.
#ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
COMPLETION_WAITING_DOTS="true"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load? (plugins can be found in ~/.oh-my-zsh/plugins/*)
# Custom plugins may be added to ~/.oh-my-zsh/custom/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(
  docker
  docker-compose
  git
  history
  last-working-dir
  pip
  python
  screen
  thefuck
)
source $ZSH/oh-my-zsh.sh

# User configuration

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#

alias zshcfg="mcedit ~/.zshrc"
alias ohmyzsh="mcedit ~/.oh-my-zsh"


### keybindings ###
# vi mode
bindkey -e
# home/end
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line


### aliases / functions ###
# default settings
alias ls='ls -h --color --classify'
alias ll='ls -alh --color --classify'
alias lg='lazygit'
alias grep='grep --color=auto'
alias nano='nano --nowrap -B -c'
alias hg='history | grep'
alias nf='neofetch'
alias mce='mcedit'

# ignore dangerous commands from history and make them safer
alias rm='rm -I'
alias chmod=' chmod -c'
alias chown=' chown -c'
alias shred=' shred -u -z'

# nginx alias
alias cdngx='cd /etc/nginx/conf.d/'
alias ngx+='sudo systemctl start nginx'
alias ngx-='sudo systemctl stop nginx'
alias ngx#='sudo systemctl restart nginx'
alias ngxr='sudo systemctl reload nginx'
alias ngxs='sudo systemctl status nginx'
alias ngx!='sudo nginx -t'
alias showcerts='certbot certificates'

# system alias
alias prepatch='sudo screen -S sysupdate'
alias cleandlog='sudo cat /dev/null > /var/lib/docker/containers/*/*-json.log'
alias syspatch='sudo journalctl --vacuum-time=7d && sudo journalctl --vacuum-size=2G && sudo apt -y update && sudo apt -y dist-upgrade && sudo apt -y autoremove && sudo apt -y autoclean && docker system prune && docker volume prune'
alias syspatcha='sudo journalctl --vacuum-time=7d && sudo journalctl --vacuum-size=2G && sudo dnf -y update && docker system prune && docker volume prune'
alias dusort='du /var --max-depth=1 | sort -nr | cut -f2 | xargs -n 1 du -hs'
alias f2b='fail2ban-client status '
alias ups='sudo $HOME/getScripts.py && sudo cp $HOME/myodoo-docker/getScripts.py $HOME/ && source ~/.zshrc'

# MyOdoo alias
alias dobk='$HOME/container2backup.py'
alias doup='$HOME/update_docker_myodoo.py'
alias edbk='mcedit $HOME/container2backup.csv'
alias edup='mcedit $HOME/docker2update.csv'


# Docker alias
alias dk="docker "
alias dps="docker ps -a"
alias dpi="docker images"
alias dkpsf='docker inspect  -f "{{.Name}} {{.Config.Cmd}}" $(docker ps -a -q)'
alias dkps="docker ps -a"
alias dkpi="docker images"
alias dkcp="docker-compose "
alias dkcpup="docker-compose up -d"
alias dkcpdown="docker-compose down"
alias dkprs="docker system prune"
alias dkprv="docker volume prune"
alias dkpri="docker image prune -a"


if [ -f /usr/bin/neofetch ]
then
    neofetch
fi

cd $HOME
