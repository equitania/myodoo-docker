# bash for ubuntu 20.x powered by MyOdoo.de
# Version 1.0.1
# Date 22.12.2020

# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for example

export HISTTIMEFORMAT="%F %T "

# If not running interactively, don't do anything
[ -z "$PS1" ] && return

# don't put duplicate lines in the history. See bash(1) for more options
# ... or force ignoredups and ignorespace
HISTCONTROL=ignoredups:ignorespace

# append to the history file, don't overwrite it
shopt -s histappend

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=1000
HISTFILESIZE=2000

# check the window size after each command and, if necessary,
# update the values of LINES and COLUMNS.
shopt -s checkwinsize

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "$debian_chroot" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
#force_color_prompt=yes

if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt force_color_prompt

# If this is an xterm set the title to user@host:dir
case "$TERM" in
xterm*|rxvt*)
    PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"
    ;;
*)
    ;;
esac

# enable color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    #alias dir='dir --color=auto'
    #alias vdir='vdir --color=auto'

    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

# some more ls aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# Alias definitions.
# You may want to put all your additions into a separate file like
# ~/.bash_aliases, instead of adding them here directly.
# See /usr/share/doc/bash-doc/examples in the bash-doc package.

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
#if [ -f /etc/bash_completion ] && ! shopt -oq posix; then
#    . /etc/bash_completion
#fi

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
alias syspatch='sudo journalctl --vacuum-time=7d && sudo journalctl --vacuum-size=2G && sudo apt -y update && sudo apt -y dist-upgrade && sudo apt -y autoremove && sudo apt -y autoclean'
alias bash#='source ~/.bashrc'
alias dnw='docker network inspect ownerp-net >/dev/null 2>&1 || \
    docker network create ownerp-net'
# docker volume Odoo live
alias dnw='docker network inspect ownerp-net >/dev/null 2>&1 || \
    docker network create ownerp-net'
# docker volume Odoo test
alias dvol='docker volume inspect vol-odoo-live >/dev/null 2>&1 || \
    docker volume create vol-odoo-live'
alias dvot='docker volume inspect vol-odoo-test >/dev/null 2>&1 || \
    docker volume create vol-odoo-test'
# docker volume PostgreSQL live
alias dvpl='docker volume inspect vol-pg-live >/dev/null 2>&1 || \
    docker volume create vol-pg-live'
# docker volume PostgreSQL test
alias dvpt='docker volume inspect vol-pg-test >/dev/null 2>&1 || \
    docker volume create vol-pg-test'
# docker volume PostgreSQL test
alias dvfr='docker volume inspect vol-fast-report >/dev/null 2>&1 || \
    docker volume create vol-fast-report'

eval "$(starship init bash)"
cd $HOME