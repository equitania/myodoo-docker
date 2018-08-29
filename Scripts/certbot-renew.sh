#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate und nginx logs älter als 14 Tage löschen
# Einstellung für crontab -e
# Jeden Samstag um 3 Uhr sollen die Zertifikate geprüft werden
#0 3 * * 6  /root/certbot-renew.sh | tee /var/log/letsencrypt-renew.log>/dev/null 2>&1



echo "nginx stop"
service nginx stop
echo "certbot renew"
$HOME/certbot/letsencrypt-auto renew
echo "delete nginx log files older than 7 days = DSGVO konform"
find /var/log/nginx/ -type f -mtime +7 | xargs rm
echo "nginx start"
service nginx start
service nginx status

exit 0
