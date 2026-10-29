# Fish Shell Configuration - ownERP Server Environment
# Version 1.1.0 | 29.10.2026
# https://github.com/equitania/myodoo-docker
#
# This is the minimal entry point. All configuration is modular:
# - conf.d/00-env.fish         : Environment variables
# - conf.d/10-path.fish        : PATH configuration
# - conf.d/20-tools.fish       : Tool initialization (Zoxide, Starship)
# - conf.d/30-aliases-*.fish   : Alias modules
# - conf.d/40-completions.fish : Dynamic completions
# - conf.d/50-prompt.fish      : Prompt and startup

# Sourced from bash or zsh (`source ~/.config/fish/config.fish`), fish syntax
# fails with "set: -g: invalid option". This line parses in all three shells
# and leaves fish (which has neither variable) with status 0 - ups returns it.
test -z "$BASH_VERSION$ZSH_VERSION" || ! echo "Das ist die Fish-Konfiguration - Fish starten mit: exec fish" >&2 || return 0

# Fish automatically sources all files in conf.d/
# No additional configuration needed here

# Prevent greeting message
set -g fish_greeting
