#ZSH powered by MyOdoo.de
# Version 2.0.0
# Date 21.12.2020

# If you come from bash you might have to change your $PATH.
export PATH=$HOME/bin:/usr/local/bin:$PATH


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