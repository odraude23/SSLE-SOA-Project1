#!/bin/bash
set -e

mkdir -p /var/log/mail /var/mail/smartcity.local /var/run/spamd
touch /var/log/mail/mail.log
chown spamd:spamd /var/run/spamd 2>/dev/null || true

# Start rsyslog so Postfix can write to /var/log/mail/mail.log
rsyslogd || true

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

# Start Postfix
postfix start

echo "[mail-server] Postfix + SpamAssassin started"
echo "[mail-server] Accepting mail for smartcity.local on :25"

# Keep container alive and forward mail log to stdout for Docker logs
tail -f /var/log/mail/mail.log
