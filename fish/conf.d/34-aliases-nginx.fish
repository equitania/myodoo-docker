# Nginx Aliases
# Version 1.0.0 | 28.01.2026

# Navigation
alias cdngx='cd /etc/nginx/conf.d/'

# Service control
alias ngx+='sudo systemctl start nginx'
alias ngx-='sudo systemctl stop nginx'
alias 'ngx#'='sudo systemctl restart nginx'
alias ngxr='sudo systemctl reload nginx'
alias ngxs='sudo systemctl status nginx'

# Configuration
alias 'ngx!'='sudo nginx -t'
alias ngxl='sudo nginx -t -c /etc/nginx/nginx.conf'
alias ngxset='nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/'

# SSL certificates
alias showcerts='certbot certificates'
