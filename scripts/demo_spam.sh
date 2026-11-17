#!/bin/bash
# Demo script — Threat 3: Email Spam / Alert Flood using token stolen in Threat 2.
# Requires apt_attack to have run first (token saved to /root/sc_token.txt).
# Usage: bash scripts/demo_spam.sh

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)

if [ -z "$SC_IP" ]; then
    echo "[!] Could not resolve smartcity-services IP. Is the container running?"
    exit 1
fi

echo "=== Threat 3 — Email Spam / Alert Flood Demo ==="
echo "  Target : http://$SC_IP:5500 (alert-service)"
echo "  Sending 30 fake critical readings in ~10s. Watch Grafana:"
echo "    - Spam Alerts counter             → turns red"
echo "    - Alert Emails Sent counter       → turns red"
echo "    - Alert Email Rate chart          → spike above 10/min threshold"
echo "    - Wazuh Alerts table              → rule 100300 + 100301 appear"
echo "    - Ops Portal Inbox                → flooded with alert emails"
echo ""

incus exec attacker -- python3 /root/poc/spam_attack.py \
    --target "http://$SC_IP:5500" \
    --count 30 \
    --interval 0.3
