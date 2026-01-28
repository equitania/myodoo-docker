# System Aliases (Cross-Platform Base)
# Version 1.0.0 | 28.01.2026

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

# Bat/Batcat (syntax highlighting cat)
if command -q batcat
    alias bat='batcat'
end
