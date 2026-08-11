# Update Odoo containers
# Version 1.0.0 | 11.08.2026

function doup --description "Update Odoo containers (TUI when enabled)"
    # Three conditions, all of them required, because each one protects a
    # different caller:
    #   no arguments    - `doup -s live-odoo` must reach the runner untouched
    #   interactive     - a cron job must never end up waiting inside a TUI
    #   marker present  - the TUI is opt-in per server until it has proven itself
    if test (count $argv) -eq 0; and status is-interactive; and test -f $HOME/.ownerp_tui_default
        $HOME/ownerp_tui.py
    else
        $HOME/update_docker_odoo.py $argv
    end
end
