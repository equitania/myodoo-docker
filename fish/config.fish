# Fish Shell Configuration - ownERP Server Environment
# Version 1.0.0 | 28.01.2026
# https://github.com/equitania/myodoo-docker
#
# This is the minimal entry point. All configuration is modular:
# - conf.d/00-env.fish         : Environment variables
# - conf.d/10-path.fish        : PATH configuration
# - conf.d/20-tools.fish       : Tool initialization (Zoxide, Starship)
# - conf.d/30-aliases-*.fish   : Alias modules
# - conf.d/40-completions.fish : Dynamic completions
# - conf.d/50-prompt.fish      : Prompt and startup

# Fish automatically sources all files in conf.d/
# No additional configuration needed here

# Prevent greeting message
set -g fish_greeting
