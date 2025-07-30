# Codebase Structure

## Root Directory Structure
```
myodoo-docker/
├── LICENSE                    # License file
├── ReadMe.md                  # Main documentation
├── CLAUDE.md                  # Claude Code instructions
├── getScripts.py              # Main installation script (v6.7.2)
├── requirements.txt           # Python dependencies (empty)
├── packages.txt               # System package versions
├── .zshrc                     # ZSH configuration with aliases
├── .gitignore                 # Git ignore patterns
├── config/                    # Configuration files
├── scripts/                   # Core automation scripts
├── Dockerfiles/               # Docker configurations
├── .serena/                   # Serena MCP configuration
├── .claude/                   # Claude configuration
└── worktrees/                 # Git worktrees
```

## Key Script Components

### Core Scripts (`/scripts/`)
- **container2backup.py** (v4.3.0) - Automated backup system
- **update_docker_myodoo.py** - Container update management
- **restore-zip.sh** - Backup restoration
- **ssl-renew.sh** - SSL certificate renewal
- **cleanup-weblogs.py** - Log cleanup automation

### Configuration Files (`/config/`)
- **backup_config.yaml** - Backup configuration
- **backup_credentials.yaml** - Backup credentials (example provided)

### Docker Configurations (`/Dockerfiles/`)
- **v12-myodoo/** - Odoo 12 Docker setup
- **v13-myodoo/** - Odoo 13 Docker setup
- **v14-myodoo/** - Odoo 14 Docker setup
- **v16-odoo/** - Odoo 16 Docker setup
- **v18-odoo/** - Odoo 18 Docker setup
- **ngx-conf/** - Nginx configuration templates

## Architecture Patterns
- **Version-based organization** for Dockerfiles
- **YAML-first configuration** management
- **Shell alias integration** for productivity
- **Caching system** for version information
- **Error recovery mechanisms** for installations