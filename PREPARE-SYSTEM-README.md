# prepare-system.py - System Preparation Script

Version: 1.2.1
Date: 19.11.2025

## Changelog

### Version 1.2.1 (19.11.2025)
- **Changed**: Claude CLI installation now uses official claude.ai installer (curl method)
- **Improved**: npm installation as fallback method for Claude CLI
- **Fixed**: More reliable Claude CLI installation process

### Version 1.2.0 (19.11.2025)
- **Added**: Fish shell installation and configuration
- **Added**: Starship prompt installation with automatic shell integration
- **Added**: Shell change notification (fish shell)
- **Improved**: Integrated pipx installation into essential packages
- **Improved**: Streamlined installation workflow

### Version 1.1.1 (19.11.2025)
- **Removed**: software-properties-common (not available in Debian 13+, not needed)
- **Fixed**: Unused variable warnings in code quality checks

### Version 1.1.0 (19.11.2025)
- **Added**: Lazygit installation with automatic architecture detection
- **Added**: Node.js 20.x installation from NodeSource repository
- **Added**: Claude Code CLI installation via npm
- **Added**: Automatic dependency resolution (Node.js for Claude CLI)
- **Improved**: Fallback to user-level installation when sudo fails

### Version 1.0.2 (19.11.2025)
- **Fixed**: Optional packages now handled gracefully (software-properties-common, etc.)
- **Fixed**: Python 3.14 DeprecationWarning for tar.extractall() with data filter
- **Improved**: Better distinction between required and optional packages
- **Improved**: Clearer log messages for skipped optional packages

### Version 1.0.1 (19.11.2025)
- **Improved**: Better pip upgrade error handling
- **Improved**: Detection of externally-managed Python environments
- **Improved**: More informative log messages for permission issues

### Version 1.0.0 (19.11.2025)
- Initial release
- Essential system package installation
- Fastfetch and zoxide installation
- Fish shell support
- Smart caching system

## Description

A standalone system preparation script that installs essential tools and libraries for Linux development environments. This script focuses purely on system setup without copying project-specific files.

## Features

- **Fish Shell Support**: Automatically configures Fish shell environment
- **Essential Tools Installation**:
  - fastfetch (system information tool)
  - zoxide (smart directory navigation)
  - pipx (Python application isolation)
  - lazygit (terminal UI for git)
  - starship (cross-shell prompt)
  - Node.js 20.x and Claude Code CLI
- **PATH Configuration**: Automatically configures `~/.local/bin` in Fish config
- **Cache System**: Smart caching of version information (24h expiry)
- **Retry Mechanism**: Automatic retry for network operations
- **Logging**: Comprehensive logging to `prepare-system.log`

## Prerequisites

- Python 3.6 or higher
- Ubuntu/Debian-based Linux distribution
- sudo privileges for package installation
- Internet connection for downloading packages

## Installation

### Quick Start

```bash
# Download the script
curl -O https://raw.githubusercontent.com/equitania/myodoo-docker/2025/prepare-system.py

# Make it executable
chmod +x prepare-system.py

# Run the script
sudo python3 prepare-system.py
```

### From Repository

```bash
# Clone the repository
git clone -b 2025 https://github.com/equitania/myodoo-docker.git

# Run the script
cd myodoo-docker
sudo python3 prepare-system.py
```

## Usage

### Basic Usage

```bash
sudo python3 prepare-system.py
```

### Advanced Options

```bash
# Enable debug logging
sudo python3 prepare-system.py --debug

# Clear cache before running
sudo python3 prepare-system.py --clear-cache

# Disable cache for this run
sudo python3 prepare-system.py --no-cache

# Show help
python3 prepare-system.py --help
```

### Environment Variables

```bash
# Enable debug logging via environment variable
export PREPARE_SYSTEM_DEBUG=1
sudo -E python3 prepare-system.py
```

## What Gets Installed

### System Packages

#### Required Packages
- python3-venv
- python3-pip
- git
- curl
- wget
- ca-certificates

#### Optional Packages (installed if available)
- gnupg
- lsb-release
- apt-transport-https

### Shell Packages
- **fish**: Modern, user-friendly command-line shell
- **pipx**: Python application isolation tool

### Development Tools

- **starship**: Fast, customizable shell prompt
  - Installed via official installer script
  - Automatically configured for Fish
  - Cross-shell compatible

- **fastfetch**: Fast system information tool
  - Auto-detects architecture (amd64, arm64, armhf, armel)
  - Installs latest version from GitHub releases
  - Location: `/usr/local/bin/fastfetch` or `~/.local/bin/fastfetch`

- **zoxide**: Smart directory navigation
  - Auto-detects architecture (x86_64, aarch64, armv7)
  - Installs to `~/.local/bin/zoxide`
  - Automatically configures shell integration

- **lazygit**: Terminal UI for git commands
  - Auto-detects architecture (x86_64, arm64)
  - Installs latest version from GitHub releases
  - Location: `/usr/local/bin/lazygit` or `~/.local/bin/lazygit`
  - Fallback to user installation if sudo unavailable

- **Node.js**: JavaScript runtime (version 20.x)
  - Installed from NodeSource official repository
  - Includes npm package manager
  - System-wide installation to `/usr/bin/node`

- **Claude Code CLI**: AI-powered coding assistant
  - Installed via official claude.ai installer (curl method)
  - Fallback to npm installation if curl method fails
  - Creates `~/.claude` directory for configuration
  - Location: `~/.local/bin/claude` or npm global bin
  - Update with: `claude update`

### Shell Configuration

The script automatically configures Fish shell:
- Creates/updates `~/.config/fish/config.fish`
- Adds PATH configuration: `set -gx PATH ~/.local/bin $PATH`
- Adds zoxide initialization: `zoxide init fish | source`
- Adds starship prompt initialization: `starship init fish | source`

## Cache System

The script caches version information to reduce API calls:
- **Cache Location**: `~/.cache/prepare-system/`
- **Cache Expiry**: 24 hours
- **Cached Data**: GitHub release information, package versions

### Cache Management

```bash
# Clear all cache
python3 prepare-system.py --clear-cache

# Run without using cache
python3 prepare-system.py --no-cache
```

## Logging

All operations are logged to:
- **Console**: INFO level and above
- **File**: `prepare-system.log` in current directory

### Log Levels
- **INFO**: Normal operations
- **WARNING**: Non-critical issues
- **ERROR**: Critical failures
- **DEBUG**: Detailed diagnostic information (use `--debug` flag)

## Differences from getScripts.py

| Feature | getScripts.py | prepare-system.py |
|---------|---------------|-------------------|
| Repository cloning | ✅ Yes | ❌ No |
| Script copying | ✅ Yes (container2backup, etc.) | ❌ No |
| Config files | ✅ Fish config | ✅ PATH only |
| Tool installation | ✅ All tools | ✅ Essential tools only |
| Package installation | ✅ PyPI packages | ✅ System packages only |
| DNS optimization | ✅ Yes | ❌ No |
| Purpose | Project setup | System preparation |

## Architecture Support

### Fastfetch
- amd64 (x86_64)
- arm64 (aarch64)
- armhf (armv7l)
- armel (armv6l)

### Zoxide
- x86_64
- aarch64 (arm64)
- armv7

## Troubleshooting

### Permission Denied
```bash
# Make sure to run with sudo
sudo python3 prepare-system.py
```

### Network Errors
```bash
# Check internet connection
ping github.com

# Retry with debug mode
sudo python3 prepare-system.py --debug
```

### Cache Issues
```bash
# Clear cache and retry
python3 prepare-system.py --clear-cache
sudo python3 prepare-system.py
```

### Shell Not Detected
```bash
# Check SHELL environment variable
echo $SHELL

# Manually set if needed
export SHELL=/usr/bin/fish
sudo -E python3 prepare-system.py
```

## Post-Installation

After successful installation:

1. **Reload Fish shell configuration**:
   ```bash
   source ~/.config/fish/config.fish
   ```

2. **Verify installations**:
   ```bash
   fastfetch --version
   zoxide --version
   pipx --version
   lazygit --version
   starship --version
   node --version
   claude --version
   ```

3. **Test zoxide**:
   ```bash
   # Navigate to a directory
   cd ~/Documents

   # Use zoxide
   z Doc  # Should jump to ~/Documents
   ```

## Contributing

This script is part of the myodoo-docker repository maintained by Equitania Software GmbH.

- Repository: https://github.com/equitania/myodoo-docker
- Branch: 2025
- Issues: https://github.com/equitania/myodoo-docker/issues

## License

AGPL-3.0 License

Copyright (C) 2014-now Equitania Software GmbH

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation.

## See Also

- **getScripts.py**: Full project setup script with Docker configurations
- **container2backup.py**: Automated backup system for Docker containers
- **update_docker_myodoo.py**: Docker container update management

## Support

For issues, questions, or contributions:
- Create an issue on GitHub
- Contact: Equitania Software GmbH
- Website: https://www.equitania.de
