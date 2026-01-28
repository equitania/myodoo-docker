# Dynamic Completions
# Version 1.0.0 | 28.01.2026

# Docker completions (Fish has built-in support)
# Additional custom completions can be added here

# Git branch completion for custom aliases
complete -c gco -f -a '(git branch --format="%(refname:short)")'
complete -c gbd -f -a '(git branch --format="%(refname:short)")'
complete -c gbD -f -a '(git branch --format="%(refname:short)")'

# Docker container name completion for exec aliases
complete -c exec-live -f
complete -c exec-test -f

# Backup directory completion
complete -c cpbk -f -a '(ls /opt/backups/docker/ 2>/dev/null)'
