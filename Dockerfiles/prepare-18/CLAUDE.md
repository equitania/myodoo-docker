# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**MyOdoo Prepare-V18** ist ein Docker Base-Image für Odoo 18-Installationen. Es enthält alle notwendigen System- und Python-Abhängigkeiten für Odoo 18, aber nicht Odoo selbst - damit dient es als Foundation für produktive Odoo-Container.

## Key Architecture

### Multi-Stage Docker Build
- **Builder Stage**: Vollständige Build-Umgebung mit allen Abhängigkeiten
- **Production Stage**: Minimales Runtime-Image mit nur notwendigen Komponenten
- **Platform Support**: Intel/AMD64 only

### Core Components
- **Base**: python:3.12.x-bookworm (Debian Bookworm)
- **Localization**: German (de_DE.UTF-8, Europe/Berlin timezone)
- **System Dependencies**: PostgreSQL client, wkhtmltopdf, Node.js, fonts
- **Python Libraries**: 120+ packages optimized for Odoo 18 compatibility

### Version Management
Tag format: `YY.MM.DD-PYTHON_VERSION` (e.g., `25.02.25-3.12.11`)
- Build date wird automatisch aus GitLab CI generiert
- Python version wird aus Dockerfile ARG extrahiert

## Development Commands

### Build and Test Locally
```bash
# Build image locally
docker build -t myodoo/prepare-v18:local .

# Test image functionality
docker run -it myodoo/prepare-v18:local python3 -c "import psycopg2, lxml, requests; print('Dependencies OK')"

# Check installed packages
docker run -it myodoo/prepare-v18:local pip list

# Check wkhtmltopdf installation
docker run -it myodoo/prepare-v18:local wkhtmltopdf --version
```

### Standard Building (Local)
```bash
# Build image locally
docker build -t myodoo/prepare-v18:test .

# Build and push to registry
docker build -t myodoo/prepare-v18:latest .
docker push myodoo/prepare-v18:latest
```

## GitLab CI/CD Pipeline

### Pipeline Stages
1. **Build image**: Standard Docker build und Registry push
2. **Push to Docker Hub**: Verification und cleanup
3. **Update Docs**: (Optional) Documentation updates

### Key Features
- **Automatic versioning**: Datum wird zur Build-Zeit generiert
- **Intel/AMD64 only**: Simplified single-platform build
- **Cache optimization**: Docker build cache für faster builds
- **Timeout handling**: 4-hour timeout für large builds

### Environment Variables Required
- `DOCKER_HUB_USER`: Docker Hub username
- `DOCKER_HUB_PASSWORD`: Docker Hub password
- `CI_REGISTRY_*`: GitLab registry credentials (automatisch verfügbar)

## Python Dependencies Management

### Version Strategy
Requirements.txt verwendet **conditional dependencies** basierend auf Python version:
```python
# Example pattern
cryptography==3.4.8; python_version < '3.12'
cryptography==42.0.8 ; python_version >= '3.12'
```

### Key Package Categories
- **Database**: psycopg2, python-ldap
- **Web**: Werkzeug, Jinja2, requests, zeep
- **Documents**: openpyxl, Pillow, reportlab, lxml, PyPDF2
- **Utilities**: num2words, python-stdnum, qrcode, pandas, numpy
- **APIs**: openai, python-gitlab, deepl, nextcloud-api-wrapper

### Adding Dependencies
1. Edit `requirements.txt` mit version conditions
2. Test build lokal mit verschiedenen Python versions
3. Verify no conflicts mit existing packages

## Critical Notes

### Intel-Specific Components
- **wkhtmltopdf**: AMD64 build von ownerp.io server
- **Node.js**: Installed von NodeSource repository
- **PostgreSQL client**: Latest version von apt.postgresql.org

### Security Considerations
- Custom wkhtmltopdf builds von trusted source (rm.ownerp.io)
- GPG verification für PostgreSQL repository
- No sensitive data in final image (multi-stage build)

### Performance Optimizations
- **Multi-stage build**: Removes build tools from final image
- **Layer caching**: Structured für optimal Docker layer caching
- **Intel-optimized**: Single platform für faster builds

## Common Issues

### wkhtmltopdf Installation
Falls wkhtmltopdf build fails:
```bash
# Verify download URL ist accessible:
curl -I https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb

# Test direct download:
wget https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
```

### Python Dependencies Conflicts
Bei dependency conflicts:
1. Check requirements.txt für version conditions
2. Verify Python version logic
3. Test mit clean environment: `docker build --no-cache`

### Build Timeouts
GitLab CI build timeouts (4h limit):
- Monitor BuildX cache utilization
- Check für stuck network operations
- Verify base image availability