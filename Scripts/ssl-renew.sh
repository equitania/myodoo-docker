#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate und nginx logs älter als 14 Tage löschen
# Einstellung für crontab -e
# Renew certificates every wednesday at 0:00 h
# 0 0 * * 3 /root/ssl-renew.sh >/dev/null 2>&1

echo "nginx stop"
sudo service nginx stop
echo "certbot renew"
sudo certbot renew
echo "nginx start"
sudo service nginx start
sudo service nginx status

exit 0
