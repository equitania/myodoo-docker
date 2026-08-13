# Update Odoo containers
# Version 2.0.0 | 13.08.2026

# A function rather than an alias for one reason only: it used to choose
# between the TUI and the runner. That choice is gone — ownerp_tui.py was
# withdrawn on 13.08.2026 and the console that replaced it starts nothing, so
# `doup` goes straight to the runner again.
#
# Kept as a function anyway, because an alias here would be shadowed by the
# function fish has already autoloaded on any server that has not re-sourced
# its configuration yet. One less thing to go wrong during an upgrade.
function doup --description "Update Odoo containers"
    $HOME/update_docker_odoo.py $argv
end
