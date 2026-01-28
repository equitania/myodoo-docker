# Odoo Development Aliases
# Version 1.0.0 | 28.01.2026

# Odoo container shortcuts (customize container names as needed)
alias odoo-shell='docker exec -ti odoo-server bash -l'
alias odoo-logs='docker logs -f odoo-server'
alias odoo-restart='docker restart odoo-server'

# Database shortcuts (customize database name as needed)
alias pg-shell='docker exec -ti postgres-db psql -U ownerp'
