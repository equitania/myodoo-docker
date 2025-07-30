# Essential Commands for myodoo-docker Development

## Initial Setup Commands
```bash
# First-time installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# Branch-specific installation (2025 branch)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2025 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```

## Daily Operation Commands
```bash
# Backup Management
dobk                    # Run backup (container2backup.py)
edbk                    # Edit backup configuration
llbk                    # View backup directory

# Container Updates
doup                    # Update Docker containers (old script)
doup2                   # Update Docker containers (new script)
edup                    # Edit update configuration

# Docker Management
dps                     # List running containers (formatted)
dpsall                  # Extended container listing
dk                      # Docker shortcut
dkstop                  # Stop all containers
dkrm                    # Remove all containers (CAUTION)
```

## System Administration
```bash
# Nginx Management
cdngx                   # Go to nginx config directory
ngx+                    # Start nginx
ngx-                    # Stop nginx
ngx#                    # Restart nginx
ngxr                    # Reload nginx configuration
ngx!                    # Test nginx configuration

# System Maintenance
syspatch               # Comprehensive system update
cleandlog              # Clean Docker logs
dusort                 # Show directory sizes sorted
ups                    # Update ownERP scripts
```

## Development Tools
```bash
# File Editing
mce filename           # Edit with mcedit
tilde filename         # Edit with tilde editor

# Version Control
lg                     # Launch lazygit (if available)

# System Information
ff                     # Show system info with fastfetch
```

## Safety Commands (Use with Extreme Caution)
```bash
# Docker Cleanup (VERIFY FIRST)
dkprs                  # Docker system prune
dkprv                  # Docker volume prune
dkprf                  # Complete system cleanup
dkprfa                 # Complete cleanup including volumes
```