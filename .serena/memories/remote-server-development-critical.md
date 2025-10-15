# CRITICAL: Remote Server Development Environment

**ABSOLUTE RULE**: VSCode Server and all Docker development runs on REMOTE SERVERS, NOT locally on macOS!

## What This Means

1. **NEVER run local Docker commands** like:
   - `docker-compose restart`
   - `docker ps`
   - `docker exec`
   - Any Docker management commands

2. **NEVER test or verify Docker status locally** - it won't work because:
   - Docker containers run on remote servers
   - Local machine (macOS) doesn't have access to remote Docker daemon
   - Commands will fail or show wrong information

3. **Configuration changes only**:
   - Modify docker-compose.yml files
   - Edit .env files
   - Update configuration files
   - Server administrators handle container restarts

4. **Diagnosis via logs and config**:
   - Analyze configuration files
   - Read log files if accessible
   - Suggest configuration changes
   - Don't attempt container operations

## Scripts Affected

All scripts in `/root/myodoo-docker/` and related repositories run on remote servers:
- getScripts.py
- container2backup.py
- update_docker_myodoo.py
- All shell aliases (doup, dobk, ngx*, etc.)

## Current Issue

The error "Directory /root/myodoo-docker does not exist" happens on the REMOTE SERVER, not locally. This requires analyzing the script logic and fixing the repository path handling.
