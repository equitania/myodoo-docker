#!/bin/bash
# Einstellung für crontab -e
# Jeden Tag um 3 Uhr sollen die Logs gelöscht werden, die älter sind als 7 Tage
# * 3 * * * root /root/cleanup-weblogs.sh >/dev/null 2>&1

echo "delete nginx log files older than 7 days = DSGVO konform"
find /var/log/nginx/ -type f -mtime +7 | xargs rm

exit 0
