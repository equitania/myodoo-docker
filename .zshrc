#ZSH powered by MyOdoo.de
# Version 2.0.1
# Date 01.01.2021

# If you come from bash you might have to change your $PATH.
export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
export ZSH=$HOME/.oh-my-zsh

# Set name of the theme to load. Optionally, if you set this to "random"
# it'll load a random theme each time that oh-my-zsh is loaded.
# See https://github.com/robbyrussell/oh-my-zsh/wiki/Themes
#ZSH_THEME="robbyrussell"
#ZSH_THEME="gnzh"
#ZSH_THEME="juanghurtado"
ZSH_THEME="bira"
#ZSH_THEME="muse"
#ZSH_THEME="random"

# Set list of themes to load
# Setting this variable when ZSH_THEME=random
# cause zsh load theme from this variable instead of
# looking in ~/.oh-my-zsh/themes/
# An empty array have no effect
ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "gnzh" "juanghurtado" "muse" )

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
export UPDATE_ZSH_DAYS=13

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
  git git-extras history jsontools last-working-dir pip python screen web-search ansible docker
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

alias zshcfg="nano -B ~/.zshrc"
alias ohmyzsh="nano -B ~/.oh-my-zsh"


### keybindings ###
# vi mode
bindkey -e
# home/end
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line


### aliases / functions ###
# default settings
alias ls='ls --color --classify'
alias ll='exa --long --header'
alias lg='exa --long --header --git'
alias grep='grep --color=auto'
alias nano='nano --nowrap -B -c'
alias hg='history | grep'

# ignore dangerous commands from history and make them safer
alias rm='rm -I'
alias chmod=' chmod -c'
alias chown=' chown -c'
alias shred=' shred -u -z'
#alias cp='cp -i'
#alias mv='mv -i'

# server alias
alias cdngx='cd /etc/nginx/conf.d/'
alias ngx+='sudo systemctl start nginx'
alias ngx-='sudo systemctl stop nginx'
alias ngx#='sudo systemctl restart nginx'
alias ngxr='sudo systemctl reload nginx'
alias ngxs='sudo systemctl status nginx'
alias ngx!='sudo nginx -t'
alias dps='sudo docker ps -a'
alias dpsfull='sudo docker inspect  -f "{{.Name}} {{.Config.Cmd}}" $(docker ps -a -q)'
alias dpi='sudo docker images'
alias syspatch='sudo journalctl --vacuum-time=7d && sudo journalctl --vacuum-size=2G && sudo apt -y update && sudo apt -y dist-upgrade && sudo apt -y autoremove && sudo apt -y autoclean'
alias dpv='sudo docker volume ls'
alias dobk='$HOME/container2backup.py'
alias dobkc='$HOME/container2backup.py'
alias doup='$HOME/update_docker_myodoo.py'
alias edbk='nano -B $HOME/container2backup.csv'
alias edbkc='nano -B $HOME/container2backup.csv'
alias edup='nano -B $HOME/docker2update.csv'
alias showcerts='certbot certificates'
alias ups='sudo $HOME/getScripts.py && sudo cp $HOME/myodoo-docker/getScripts.py $HOME/'
alias dusort='du /var --max-depth=1 | sort -nr | cut -f2 | xargs -n 1 du -hs'