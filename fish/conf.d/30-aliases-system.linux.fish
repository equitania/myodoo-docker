# System Aliases (Linux-Specific)
# Version 1.1.0 | 14.08.2026

# Only run on Linux
if test (uname) != Linux
    return
end

# Safety aliases for destructive commands
alias rm='rm -I'
alias chmod='chmod -c'
alias chown='chown -c'
alias shred='shred -u -z'

# System maintenance
#
# cleandlog is a function now (functions/cleandlog.fish). It used to be
#   sudo sh -c "cat /dev/null > /var/lib/docker/containers/*/*-json.log"
# which could not work: a redirect takes exactly one target and a glob yields
# many, and the docker root was hard-coded rather than read from `docker info`.
# On a host where the pattern matched nothing it reported "Directory
# nonexistent" and trimmed no log at all. An alias here would shadow the
# function, so nothing may reintroduce one under that name.
alias dusort='du /var --max-depth=1 | sort -nr | cut -f2 | xargs -n 1 du -hs'
alias f2b='fail2ban-client status'
alias prepatch='sudo screen -S sysupdate'

# Fish configuration editing
alias fishcfg='mcedit ~/.config/fish/config.fish'
