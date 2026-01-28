# Tool Initialization
# Version 1.0.0 | 28.01.2026

# Zoxide (smart cd)
if command -q zoxide
    zoxide init fish | source
end

# Starship prompt
if command -q starship
    starship init fish | source
end

# Claude CLI (if installed)
if test -f $HOME/.claude/local/claude
    alias claude="$HOME/.claude/local/claude"
end
