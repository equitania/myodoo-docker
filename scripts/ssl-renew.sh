#!/bin/bash
# ssl-renew.sh — Renew Let's Encrypt certificates (standalone, nginx-aware)
# Version 1.2.0 — 27.05.2026
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
#
# v1.2.0: nginx is restarted via nginx-cert-guard.py (--reconcile --start) instead
# of a bare `systemctl start nginx`. If a customer moved their domain away and a
# vhost is now broken, the guard quarantines just that vhost so nginx still comes
# up — instead of a single bad cert taking the whole server down. Falls back to
# `systemctl start nginx` when the guard is not present.
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

# Locate nginx-cert-guard.py (deployed to /root by getScripts.py, or alongside
# this script). The guard brings nginx up safely, isolating any vhost that would
# otherwise block the start (missing cert / non-resolving listen host).
SELF_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)"
GUARD=""
for cand in "${SELF_DIR}/nginx-cert-guard.py" /root/nginx-cert-guard.py; do
    [ -f "$cand" ] && GUARD="$cand" && break
done
if [ -z "${GUARD}" ] && command -v nginx-cert-guard.py >/dev/null 2>&1; then
    GUARD="$(command -v nginx-cert-guard.py)"
fi

# Build the post-hook: prefer the guard, fall back to a plain start.
if [ -n "${GUARD}" ]; then
    START_HOOK="python3 ${GUARD} --reconcile --start"
    echo "nginx will be brought up via guard: ${GUARD}"
else
    START_HOOK="systemctl start nginx"
    echo "nginx-cert-guard.py not found — using plain 'systemctl start nginx'."
fi

# Renew. Hooks run ONLY when a cert is actually renewed:
#   --pre-hook   : stop nginx so a standalone challenge can bind port 80
#   --deploy-hook: clear the nginx cache for each renewed cert
#   --post-hook  : bring nginx back up (via guard when available)
echo "certbot renew (nginx bounced only if a cert is due)"
"${CERTBOT}" renew \
    --pre-hook  "systemctl stop nginx" \
    --deploy-hook "rm -rf /var/cache/nginx && mkdir -p /var/cache/nginx" \
    --post-hook "${START_HOOK}"
renew_rc=$?

# Safety net: never leave nginx down. If a post-hook failed (or didn't run for an
# unexpected reason), bring nginx up via the guard (fallback: plain start).
if ! systemctl is-active --quiet nginx; then
    echo "nginx not active after renewal — bringing it up."
    if [ -n "${GUARD}" ]; then
        python3 "${GUARD}" --reconcile --start || systemctl start nginx
    else
        systemctl start nginx
    fi
fi

echo "certbot renew exit code: ${renew_rc}"
systemctl status nginx --no-pager | head -n 5
exit "${renew_rc}"
