# PATH Configuration (Linux-Specific)
# Version 1.0.0 | 28.01.2026

# Only run on Linux
if test (uname) != Linux
    exit 0
end

# Snap packages
if test -d /snap/bin
    fish_add_path --path /snap/bin
end

# Cargo/Rust
if test -d $HOME/.cargo/bin
    fish_add_path --path $HOME/.cargo/bin
end
