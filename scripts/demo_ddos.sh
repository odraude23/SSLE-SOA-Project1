#!/bin/bash
# Demo script — Threat 1: DDoS attack against ops-portal.
# Usage: bash scripts/demo_ddos.sh

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)

if [ -z "$SC_IP" ]; then
    echo "[!] Could not resolve smartcity-services IP. Is the container running?"
    exit 1
fi

TARGET="http://$SC_IP:5600"

echo "=== Threat 1 — DDoS Demo ==="
echo "  Target : $TARGET"
echo "  Sending ~2000 requests in a burst. Watch Grafana:"
echo "    - Ops Portal Request Rate / 2min  → spike"
echo "    - New Alerts / 5 min              → ~2000 alerts (rule 100001/100002)"
echo "    - DDoS Alerts counter             → increments"
echo "    - Currently Blocked IPs           → attacker IP appears"
echo ""

incus exec attacker -- python3 /root/poc/ddos_attack.py \
    --target "$TARGET"
