# System Aliases (Linux-Specific)
# Version 1.0.1 | 30.06.2026

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
alias cleandlog='sudo sh -c "cat /dev/null > /var/lib/docker/containers/*/*-json.log"'
alias dusort='du /var --max-depth=1 | sort -nr | cut -f2 | xargs -n 1 du -hs'
alias f2b='fail2ban-client status'
alias prepatch='sudo screen -S sysupdate'

# Fish configuration editing
alias fishcfg='mcedit ~/.config/fish/config.fish'
