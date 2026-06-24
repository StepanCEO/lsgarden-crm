#!/bin/sh
set -eu

echo "[cron] Starting backup cron..."

# Write crontab and start cron
echo "0 3 * * * cd /app && python manage.py backup_db >> /var/log/cron.log 2>&1" > /tmp/crontab
echo "# empty line" >> /tmp/crontab

# Install crontab
crontab /tmp/crontab

# Start cron in foreground
crond -f -l 2
