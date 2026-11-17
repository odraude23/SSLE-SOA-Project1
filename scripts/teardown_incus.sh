#!/bin/bash
# Removes both Incus containers and the shared log directory.
# Run this to start fresh before setup_incus.sh.
set -e

echo "=== Smart City SOA — Teardown ==="

for INSTANCE in smartcity-services wazuh attacker; do
    if incus info "$INSTANCE" &>/dev/null; then
        echo "[*] Deleting $INSTANCE"
        incus delete "$INSTANCE" --force
    else
        echo "[~] $INSTANCE not found, skipping"
    fi
done

for DIR in "$HOME/smartcity-shared-logs" "$HOME/wazuh-alerts-shared"; do
    if [ -d "$DIR" ]; then
        echo "[*] Removing $DIR"
        # sudo required: Wazuh writes alert files as root into the shared directory
        sudo truncate -s 0 "$DIR/alerts.json" 2>/dev/null || true
        sudo rm -rf "$DIR"
    else
        echo "[~] $DIR not found, skipping"
    fi
done

echo "=== Teardown complete. Run: bash scripts/setup_incus.sh ==="
