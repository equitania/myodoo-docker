# Prompt and Startup
# Version 1.2.0 | 14.08.2026

# Run fastfetch on interactive shell start
if status is-interactive
    if command -q fastfetch
        fastfetch
    else if command -q neofetch
        neofetch
    end
end

# Command overview — once per session, not in every pane.
#
# fastfetch above runs on every shell because it is four lines of machine state.
# This panel is fifteen, and a tmux session with six panes would print it six
# times. So it needs a gate — but not `status is-login`, which was the first
# attempt and never fired on the servers this panel exists for: operators reach
# root with `sudo su`, and `su` without `-` starts an interactive shell that is
# not a login shell. fastfetch appeared, the panel did not.
#
# An exported marker is the boundary that matches how these servers are used.
# Everything started from this shell inherits it — tmux panes, subshells, `su` —
# and stays quiet. A fresh ssh session starts without it, and so does `sudo`,
# which resets the environment: arriving as root is a new session and gets the
# panel. `help` shows it again on demand.
if status is-interactive; and not set -q OWNERP_HELP_SHOWN
    if functions -q ownerp-help
        set -gx OWNERP_HELP_SHOWN 1
        ownerp-help
    end
end

# Start in home directory
cd $HOME
