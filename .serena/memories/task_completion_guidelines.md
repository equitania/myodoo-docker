# Task Completion Guidelines

## Critical Safety Rules

### Docker Resource Management
**NEVER delete Docker resources without explicit verification**:
```bash
# ALWAYS verify first
docker ps -a | grep -E "(myodoo|odoo)"    # List project containers
docker volume ls | grep -E "(myodoo|odoo)" # List project volumes

# SAFE deletion pattern
docker rm container_name_1 container_name_2  # Specific containers only
docker volume rm volume_name_1 volume_name_2 # Specific volumes only

# NEVER use global cleanup without filters
# docker system prune -a                     # DANGEROUS
# docker volume prune                        # DANGEROUS
```

### Version and Date Management
```bash
# Before modifying any script with version header:
1. Check current date from environment (today is 2025, not 2024!)
2. Increment version number (X.Y.Z format)
3. Update date to DD.MM.YYYY format (e.g., 24.06.2025)
4. Use UTF-8 encoding for all operations
```

## Pre-Deployment Checklist

### Code Validation
```bash
# Python syntax check
python3 -m py_compile script_name.py

# YAML configuration validation
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Test script functionality (if dry-run available)
./script_name.py --dry-run
```

### Configuration Verification
```bash
# Backup configuration
tilde ~/container2backup.yaml      # Verify backup settings

# Docker configuration
docker-compose config               # Validate docker-compose files

# Nginx configuration (if applicable)
nginx -t                           # Test nginx syntax
```

## Post-Completion Actions

### Version Control
```bash
# Commit with proper prefix
git add .
git commit -m "[FIX] Description of changes"   # or [ADD], [CHG]
git push origin branch_name
```

### System Updates
```bash
# Update script repository
ups                                # Update ownERP scripts

# Reload shell configuration
source ~/.zshrc                    # Apply alias changes
```

### Verification Steps
```bash
# Verify installations
./getScripts.py                    # Re-run setup if needed

# Test core functionality
dobk --dry-run                     # Test backup (if available)
doup --dry-run                     # Test updates (if available)
```

## Quality Gates
1. **Syntax validation** - All Python scripts must compile
2. **Configuration validation** - YAML files must parse correctly
3. **Version consistency** - Headers match current date/version
4. **Safety verification** - Docker operations target correct resources
5. **Documentation updates** - Update relevant documentation if needed
6. **Testing** - Manual testing of critical paths
7. **Commit standards** - Proper commit message prefixes