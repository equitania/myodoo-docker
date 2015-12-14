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
alias cp='cp -i'
alias mv='mv -i'

# Shortcuts
alias cdngx='cd /etc/nginx/conf.d/'
alias ngx+='/etc/init.d/nginx start'
alias ngx-='/etc/init.d/nginx stop'
alias ngx#='/etc/init.d/nginx restart'
alias dps='docker ps -a'

export EDITOR=nano
