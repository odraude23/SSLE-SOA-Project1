#!/bin/bash
# Remove all DROP rules from the DOCKER-USER iptables chain inside smartcity-services.
# Run this to clear blocked IPs after a PoC attack test.

set -euo pipefail

CONTAINER="smartcity-services"

IPS=$(incus exec "$CONTAINER" -- iptables -L DOCKER-USER -n \
    | awk '/^DROP/{print $4}' | grep -v '^0\.0\.0\.0' || true)

if [ -z "$IPS" ]; then
    echo "[*] No blocked IPs in DOCKER-USER chain."
    exit 0
fi

echo "[*] Removing blocked IPs from $CONTAINER:"
for IP in $IPS; do
    incus exec "$CONTAINER" -- iptables -D DOCKER-USER -s "$IP" -j DROP \
        && echo "    [-] $IP unblocked"
done

echo "[+] Done."
incus exec "$CONTAINER" -- iptables -L DOCKER-USER -n
