# System Utilities and macOS Compatibility

## Darwin (macOS) Specific Considerations

### File System Commands
```bash
# Directory listing (compatible aliases in .zshrc)
ls -h --color --classify        # Linux-style listing
ll -alh --color --classify      # Detailed listing

# File operations
cp                              # Standard copy
mv                              # Standard move
rm -I                          # Interactive removal (safety alias)
```

### Package Management
- **Homebrew integration** for macOS package installations
- **Cross-platform detection** in getScripts.py
- **Version checking** adapted for different OS package managers

### Compression Tools
```bash
# Platform-specific compression handling
# macOS: Older tar version compatibility
# Linux: Full compression support
7zz                            # Preferred 7-Zip command
tar                            # With platform-specific flags
```

## Standard Unix Utilities

### Essential Commands
```bash
# Process management
ps aux                         # Process listing
kill -9 PID                    # Force kill process
htop                          # Interactive process viewer (if installed)

# Network utilities
curl                          # HTTP client
wget                          # File downloader (if available)
ping                          # Network connectivity

# Text processing  
grep --color=auto             # Pattern matching (aliased)
awk                           # Text processing
sed                           # Stream editing

# File search and management
find                          # File search
xargs                         # Command construction
du                            # Disk usage
df                            # Filesystem usage
```

### Git Integration
```bash
# Version control (with lazygit if available)
git                           # Standard git commands
lazygit                       # TUI git interface (lg alias)
```

### System Monitoring
```bash
# System information
fastfetch                     # System info (ff alias)
neofetch                      # Alternative system info (nf alias)

# Resource monitoring
dusort                        # Directory size analysis (custom alias)
```

## Platform Detection
The `getScripts.py` script includes platform detection for:
- Package manager selection (apt vs brew)
- Tool availability checking
- Platform-specific installation methods
- Compatibility adjustments for macOS vs Linux