# Project Entrypoints and Execution

## Main Entry Points

### Primary Installation Script
```bash
# Main installation and setup
./getScripts.py                    # Install all dependencies and tools
./getScripts.py --dns-check        # DNS optimization check
./getScripts.py --clear-cache      # Clear version cache
```

### Core Automation Scripts
```bash
# Backup Operations
python3 ~/container2backup.py                    # Full backup
python3 ~/container2backup.py --sql-only         # SQL-only backup
python3 ~/container2backup.py --odoo mycontainer # Specific container

# Container Updates
python3 ~/update_docker_myodoo.py               # Update containers
python3 ~/update_docker_odoo.py                 # Alternative update script

# System Maintenance
./scripts/ssl-renew.sh                           # SSL renewal
./scripts/restore-zip.sh                         # Restore from backup
./scripts/cleanup-weblogs.py                     # Log cleanup
```

### Shell Alias Integration
After running `getScripts.py`, these shortcuts become available:
```bash
# Quick Access (via .zshrc aliases)
dobk        # Run backup script
doup        # Run update script
edbk        # Edit backup config
edup        # Edit update config
```

## Configuration Entry Points

### YAML Configuration Files
```bash
# Backup Configuration
tilde ~/container2backup.yaml          # Main backup config
tilde ~/config/backup_config.yaml      # Alternative backup config

# Update Configuration  
tilde ~/docker2update.yaml             # Container update config
```

### Environment Setup
```bash
# Shell Environment
source ~/.zshrc                         # Load aliases and functions
```

## Execution Patterns
- **Root privileges required** for most system operations
- **Configuration-driven execution** via YAML files
- **Version checking** before operations
- **Logging integration** for all major operations
- **Error recovery** with graceful degradation