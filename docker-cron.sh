#!/bin/sh
set -eu

echo "[cron] Starting backup cron..."

# Write crontab and start cron
echo "0 3 * * * cd /app && /usr/local/bin/python manage.py backup_db >> /var/log/cron.log 2>&1" > /tmp/crontab
echo "# empty line" >> /tmp/crontab

# Install crontab
crontab /tmp/crontab

# Start cron in foreground
if command -v cron >/dev/null 2>&1; then
  cron -f
else
  crond -f -l 2
fi
