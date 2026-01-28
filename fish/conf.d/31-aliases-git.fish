# Git Aliases
# Version 1.0.0 | 28.01.2026

# Basic commands
alias g='git'
alias gst='git status'
alias gco='git checkout'
alias gcm='git commit -m'
alias gp='git push'
alias gl='git pull'
alias gd='git diff'
alias ga='git add'
alias gaa='git add --all'

# Log and history
alias glog='git log --oneline --decorate --graph'
alias gloga='git log --oneline --decorate --graph --all'

# Branch operations
alias gb='git branch'
alias gba='git branch -a'
alias gbd='git branch -d'
alias gbD='git branch -D'

# Stash operations
alias gsta='git stash push'
alias gstp='git stash pop'
alias gstl='git stash list'

# Reset and clean
alias grh='git reset HEAD'
alias grhh='git reset HEAD --hard'
alias gclean='git clean -fd'

# Remote operations
alias gf='git fetch'
alias gfa='git fetch --all'
alias grv='git remote -v'
