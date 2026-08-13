# System Aliases (Cross-Platform Base)
# Version 1.1.0 | 13.08.2026

# File listing
alias ls='ls -h --color --classify'
alias ll='ls -alh --color --classify'

# Search and navigation
alias grep='grep --color=auto'
alias hg='history | grep'

# Editors
alias nano='nano --nowrap -B -c'
alias mce='mcedit'

# Tools
alias lg='lazygit'
alias nf='neofetch'
alias ff='fastfetch'
# The command overview printed at login. `help` is fish's builtin (it opens the
# manual in a browser, useless on a server), so shadowing it here is deliberate.
alias help='ownerp-help'

# Bat/Batcat (syntax highlighting cat)
if command -q batcat
    alias bat='batcat'
end
