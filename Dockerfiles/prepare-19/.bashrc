# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples

# Wenn nicht interaktiv, dann nichts tun
case $- in
    *i*) ;;
      *) return;;
esac

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color|*-256color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
force_color_prompt=yes

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
    #PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u\[\033[01;33m\]@\[\033[01;36m\]\h \[\033[01;33m\]\w \[\033[01;35m\]\$ \[\033[00m\]'
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

# Aktiviere Programmvervollständigung
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

# Aktiviere einige nützliche Bash-Optionen
shopt -s checkwinsize  # Aktualisiere Fenstergröße nach jedem Befehl
shopt -s histappend    # Hänge an Verlauf an, anstatt zu überschreiben
shopt -s cmdhist       # Speichere mehrzeilige Befehle als eine Zeile

# Verlaufskonfiguration
HISTSIZE=10000
HISTFILESIZE=20000
HISTCONTROL=ignoreboth:erasedups  # Ignoriere Duplikate und Befehle mit führendem Leerzeichen

### aliases / functions ###
# default settings
alias ls='ls --color --classify'
alias ll='ls -al --color --classify'
alias l='ls --color --classify -lah'
alias grep='grep --color=auto'
alias nano='nano --nowrap -B'
alias hg='history | grep'

# ignore dangerous commands from history and make them safer
alias rm='rm -I'
alias chmod=' chmod -c'
alias chown=' chown -c'
alias shred=' shred -u -z'
alias cp='cp -i'
alias mv='mv -i'

# Nützliche Aliase für Debian/Ubuntu
alias update='sudo apt update'
alias upgrade='sudo apt upgrade'
alias install='sudo apt install'
alias remove='sudo apt remove'
alias autoremove='sudo apt autoremove'

# Shortcuts
alias cdo='cd /opt/odoo/'
alias olog='cat /opt/odoo/var/log/odoo-server.log'
alias tlog='tail -f /opt/odoo/var/log/odoo-server.log'  # Tail-Befehl zum Verfolgen des Logs
alias rolog='rm /opt/odoo/var/log/odoo-server.log'
alias edconf='nano /opt/odoo/etc/odoo.conf'

# Odoo-spezifische Funktionen
function odoo-start() {
    cd /opt/odoo/odoo-server && python3 odoo-bin -c /opt/odoo/etc/odoo.conf
}

function odoo-debug() {
    cd /opt/odoo/odoo-server && python3 odoo-bin -c /opt/odoo/etc/odoo.conf --dev=all
}

export EDITOR=nano

# odoo
alias loadtranslate='--i18n-overwrite --load-language=de_DE '
alias cleanpo='find . -type f \( -iname "*.po" ! -iname "de.po" ! -iname "ru.po" ! -iname "fr.po" ! -iname "it.po" ! -iname "es.po" ! -iname "pt.po" ! -iname "pl.po"  \) -exec rm {} \;'

