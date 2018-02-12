#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate und nginx logs älter als 14 Tage löschen
# Einstellung für crontab -e
# Jeden 15. des Monats um 3 Uhr sollen die Zertifikate geprüft werden
#00 03 15 * *  /root/certbot-renew.sh | tee /var/log/letsencrypt-renew.log


echo "nginx stop"
/etc/init.d/nginx stop
echo "certbot renew"
/root/certbot/letsencrypt-auto renew
echo "delete nginx log files older than 14 days"
find /var/log/nginx/ -type f -mtime +14 | xargs rm
echo "nginx start"
/etc/init.d/nginx start
/etc/init.d/nginx status

exit 0
