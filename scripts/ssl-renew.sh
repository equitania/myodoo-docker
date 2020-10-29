#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate und nginx logs älter als 14 Tage löschen
# Einstellung für crontab -e
# Renew certificates every wednesday at 0:00 h
# 0 0 * * 3 /root/ssl-renew.sh >> /var/log/ssl-renew.log 2>&1

echo -n "" > /var/log/ssl-renew.log

dt=$(date '+%d.%m.%Y %H:%M:%S');
echo "#######################################"
echo "Start at $dt"
echo "#######################################"

echo "nginx stop"
systemctl stop nginx
echo "certbot renew --force-renew"
certbot renew
echo "nginx start"
systemctl start nginx
systemctl status nginx