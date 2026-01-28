# Environment Variables
# Version 1.0.0 | 28.01.2026

# Locale settings
set -gx LANG en_US.UTF-8
set -gx LC_ALL en_US.UTF-8

# Editor preferences
if command -q mcedit
    set -gx EDITOR mcedit
    set -gx VISUAL mcedit
else if command -q nano
    set -gx EDITOR nano
    set -gx VISUAL nano
end

# Pager settings
set -gx LESS '-R --use-color -Dd+r$Du+b'
set -gx MANPAGER 'less -R --use-color -Dd+r -Du+b'

# Docker settings
set -gx DOCKER_BUILDKIT 1
set -gx COMPOSE_DOCKER_CLI_BUILD 1
