# Prompt and Startup
# Version 1.1.0 | 13.08.2026

# Run fastfetch on interactive shell start
if status is-interactive
    if command -q fastfetch
        fastfetch
    else if command -q neofetch
        neofetch
    end
end

# Command overview — on LOGIN only, not on every interactive shell.
#
# fastfetch above runs on every shell because it is four lines of machine state.
# This panel is fifteen, and a tmux session with six panes would print it six
# times. `status is-login` is the honest boundary: an ssh session gets it once,
# a new tmux window does not. `help` shows it again on demand.
if status is-login; and status is-interactive
    if functions -q ownerp-help
        ownerp-help
    end
end

# Start in home directory
cd $HOME
