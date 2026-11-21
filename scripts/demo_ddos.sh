#!/bin/bash
# Demo script — Threat 1: DoS attack against ops-portal.
# Uses hey (HTTP load generator) to flood the ops-portal from the attacker container.
# Usage: bash scripts/demo_ddos.sh

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)

if [ -z "$SC_IP" ]; then
    echo "[!] Could not resolve smartcity-services IP. Is the container running?"
    exit 1
fi

TARGET="http://$SC_IP:5600"

echo "=== Threat 1 — DoS Demo ==="
echo "  Target : $TARGET"
echo "  Running hey: 50 concurrent workers for 60s. Watch Grafana:"
echo "    - Ops Portal Request Rate  → spike"
echo "    - DoS Alerts counter       → increments (rule 100002)"
echo "    - Currently Blocked IPs    → attacker IP appears"
echo ""

incus exec attacker -- hey -z 60s -c 50 "$TARGET"
