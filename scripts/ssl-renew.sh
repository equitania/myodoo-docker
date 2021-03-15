#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate
# Einstellung für crontab -e
# Renew certificates every wednesday at 0:00 h
# 0 0 * * 3 /root/ssl-renew.sh | tee /var/log/ssl-renew.log >/dev/null 2>&1


dt=$(date '+%d.%m.%Y %H:%M:%S');
echo "#######################################"
echo "Start at $dt"
echo "#######################################"

echo "nginx stop"
systemctl stop nginx
echo "certbot renew --force-renew"
if [ -f /usr/local/bin/certbot ]
then
    /usr/local/bin/certbot renew --force-renew
fi
if [ -f /usr/bin/certbot ]
then
    /usr/bin/certbot renew --force-renew
fi
echo "nginx start"
systemctl start nginx
systemctl status nginx
