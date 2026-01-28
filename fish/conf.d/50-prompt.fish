# Prompt and Startup
# Version 1.0.0 | 28.01.2026

# Run fastfetch on interactive shell start
if status is-interactive
    if command -q fastfetch
        fastfetch
    else if command -q neofetch
        neofetch
    end
end

# Start in home directory
cd $HOME
