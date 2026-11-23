# Prompt and Startup
# Version 1.5.0 | 23.11.2026

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
# panel. `help` shows it again on demand. A user in getScripts' restricted
# mode gets the same panel, cut down to what works without root (ownerp-help
# chooses the variant).
#
# The maintenance cron overview (`docron --brief`) follows the panel under the
# same gate: which jobs are switched on and when each last ran is what an
# operator wants to know on arrival, and until now only `ups` showed it. Two
# guards keep the login quiet where there is nothing to report — the script is
# not there (older server; getScripts' restricted mode never delivers it), or
# the cron file is not installed yet (fresh server), where the script would
# answer with an error line.
if status is-interactive; and not set -q OWNERP_HELP_SHOWN
    if functions -q ownerp-help
        set -gx OWNERP_HELP_SHOWN 1
        ownerp-help
        if test -x $HOME/ownerp_cron.py; and test -e /etc/cron.d/myodoo-maintenance
            $HOME/ownerp_cron.py --brief
        end
    end
end

# Start in home directory
cd $HOME
