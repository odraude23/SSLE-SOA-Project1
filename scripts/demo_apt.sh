#!/bin/bash
# Demo script — Threat 2: APT / Honeypot attack against a zone aggregator.
# Usage: bash scripts/demo_apt.sh [--zone north|center|south]
#
# Default zone: north

ZONE="north"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --zone)
            ZONE="$2"
            shift 2
            ;;
        *)
            echo "[!] Unknown flag: $1"
            echo "Usage: bash scripts/demo_apt.sh [--zone north|center|south]"
            exit 1
            ;;
    esac
done

case "$ZONE" in
    north)  PORT=5100 ;;
    center) PORT=5101 ;;
    south)  PORT=5102 ;;
    *)
        echo "[!] Unknown zone '$ZONE'. Use: north, center, or south."
        exit 1
        ;;
esac

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)

if [ -z "$SC_IP" ]; then
    echo "[!] Could not resolve smartcity-services IP. Is the container running?"
    exit 1
fi

TARGET="http://$SC_IP:$PORT"

echo "=== Threat 2 — APT Demo ==="
echo "  Zone   : $ZONE"
echo "  Target : $TARGET"
echo "  5 probe rounds × 2 honeypot endpoints, 30s between rounds (~2.5 min total)."
echo "  Watch Grafana:"
echo "    - Honeypot Hits chart             → staircase (rule 100200)"
echo "    - APT Alerts counter              → increments (rule 100201 after 3 hits)"
echo "    - Currently Blocked IPs           → attacker IP appears"
echo ""

incus exec attacker -- python3 /root/poc/apt_attack.py \
    --target "$TARGET"
