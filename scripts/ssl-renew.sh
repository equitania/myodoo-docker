#!/bin/bash
# ssl-renew.sh — Renew Let's Encrypt certificates (standalone, nginx-aware)
# Version 1.1.0 — 27.05.2026
#
# Runs `certbot renew` and bounces nginx ONLY when a certificate is actually due:
# certbot's --pre-hook/--post-hook fire only when at least one cert is renewed,
# so on a normal day (nothing due) nginx is never stopped — no needless downtime.
# The previous version stopped nginx unconditionally on every run.
#
# Designed to run DAILY from /etc/cron.d/myodoo-maintenance (installed by
# setup-maintenance-cron.sh). Output is appended to /var/log/ssl-renew.log there.
#
# Renewal uses the authenticator stored in each cert's renewal config. For certs
# issued with --standalone, the pre-hook frees port 80 (stops nginx) so certbot's
# temporary listener can bind; the post-hook brings nginx back up.
##############################################################################

set -uo pipefail

dt="$(date '+%d.%m.%Y %H:%M:%S')"
echo "#######################################"
echo "Start at ${dt}"
echo "#######################################"

# Locate certbot (apt installs /usr/bin/certbot; snap/pip use /usr/local/bin).
CERTBOT="$(command -v certbot || true)"
if [ -z "${CERTBOT}" ]; then
    for c in /usr/local/bin/certbot /usr/bin/certbot; do
        [ -x "$c" ] && CERTBOT="$c" && break
    done
fi
if [ -z "${CERTBOT}" ]; then
    echo "ERROR: certbot not found (install it via the bootstrap or 'apt-get install certbot')." >&2
    exit 1
fi
echo "Using certbot: ${CERTBOT}"

# Renew. Hooks run ONLY when a cert is actually renewed:
#   --pre-hook   : stop nginx so a standalone challenge can bind port 80
#   --deploy-hook: clear the nginx cache for each renewed cert
#   --post-hook  : start nginx again
echo "certbot renew (nginx bounced only if a cert is due)"
"${CERTBOT}" renew \
    --pre-hook  "systemctl stop nginx" \
    --deploy-hook "rm -rf /var/cache/nginx && mkdir -p /var/cache/nginx" \
    --post-hook "systemctl start nginx"
renew_rc=$?

# Safety net: never leave nginx down. If a post-hook failed (or didn't run for an
# unexpected reason), make sure nginx is back up.
if ! systemctl is-active --quiet nginx; then
    echo "nginx not active after renewal — starting it."
    systemctl start nginx
fi

echo "certbot renew exit code: ${renew_rc}"
systemctl status nginx --no-pager | head -n 5
exit "${renew_rc}"
