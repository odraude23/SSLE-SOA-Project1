#!/bin/bash
set -e

mkdir -p /var/log/mail /var/mail/smartcity.local /var/run/spamd
touch /var/log/mail/mail.log
chown spamd:spamd /var/run/spamd 2>/dev/null || true

# Start Prometheus mail metrics exporter
python3 /mail_exporter.py >> /var/log/mail/exporter.log 2>&1 &

# Start SpamAssassin daemon
spamd --daemonize \
      --pidfile=/var/run/spamd/spamd.pid \
      --max-children=5 \
      --username=spamd \
      --helper-home-dir=/var/lib/spamassassin \
      --nouser-config \
      2>>/var/log/mail/spamd.log || \
spamd -d -c -m 5 -x --pidfile=/var/run/spamd/spamd.pid 2>>/var/log/mail/spamd.log || true

sleep 2

# Start Postfix — maillog_file in main.cf writes directly to /var/log/mail/mail.log (no syslog needed)
postfix start

echo "[mail-server] Postfix + SpamAssassin started"
echo "[mail-server] Accepting mail for smartcity.local on :25"

tail -f /var/log/mail/mail.log
