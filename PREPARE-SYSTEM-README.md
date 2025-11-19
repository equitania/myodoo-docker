# prepare-system.py - System Preparation Script

Version: 1.1.0
Date: 19.11.2025

## Changelog

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
- Fish and ZSH shell support
- Smart caching system

## Description

A standalone system preparation script that installs essential tools and libraries for Linux development environments. This script focuses purely on system setup without copying project-specific files.

## Features

- **Shell Detection**: Automatically detects and configures Fish or ZSH shell
- **Essential Tools Installation**:
  - fastfetch (system information tool)
  - zoxide (smart directory navigation)
  - pipx (Python application isolation)
- **PATH Configuration**: Automatically configures `~/.local/bin` in shell config
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
- software-properties-common

### Package Managers
- **pipx**: Python application isolation tool

### Development Tools

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
  - Requires Node.js (auto-installed if missing)
  - Installed globally via npm
  - Creates `~/.claude` directory for configuration
  - Location: `/usr/local/bin/claude` or user npm global bin

### Shell Configuration

#### For Fish Shell
- Creates/updates `~/.config/fish/config.fish`
- Adds PATH configuration: `set -gx PATH ~/.local/bin $PATH`
- Adds zoxide initialization

#### For ZSH/Bash
- Creates/updates `~/.zshrc`
- Adds PATH configuration: `export PATH="~/.local/bin:$PATH"`
- Adds zoxide initialization: `eval "$(zoxide init zsh)"`

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
| Config files | ✅ Full .zshrc/.config.fish | ✅ PATH only |
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
export SHELL=/usr/bin/fish  # or /usr/bin/zsh
sudo -E python3 prepare-system.py
```

## Post-Installation

After successful installation:

1. **Reload shell configuration**:
   ```bash
   # For Fish
   source ~/.config/fish/config.fish

   # For ZSH
   source ~/.zshrc
   ```

2. **Verify installations**:
   ```bash
   fastfetch --version
   zoxide --version
   pipx --version
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
