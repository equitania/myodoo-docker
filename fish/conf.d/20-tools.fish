# Tool Initialization
# Version 1.0.1 | 30.06.2026

# Zoxide (smart cd)
if command -q zoxide
    # Fish 4.x made `cd` a builtin and no longer ships
    # $__fish_data_dir/functions/cd.fish, which zoxide's init reads to clone
    # fish's cd. Pre-define the helper when that file is absent so zoxide skips
    # the failing read (no warning) and z/zi keep working.
    if not test -r $__fish_data_dir/functions/cd.fish
        if not functions --query __zoxide_cd_internal
            function __zoxide_cd_internal
                builtin cd $argv
            end
        end
    end
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
