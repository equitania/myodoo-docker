#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate
# Einstellung für crontab -e
# Jeden Samstag Nacht um 3 Uhr sollen die Zertifikate geprüft werden
# 00 03 * * 6  /root/certbot-renew.sh | tee /var/log/letsencrypt-renew.log

echo "nginx stop"
/etc/init.d/nginx stop
echo "certbot renew"
/root/certbot/letsencrypt-auto renew
echo "nginx start"
/etc/init.d/nginx start
/etc/init.d/nginx status

exit 0
