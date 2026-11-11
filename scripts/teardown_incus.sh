#!/bin/bash
# Removes both Incus containers and the shared log directory.
# Run this to start fresh before setup_incus.sh.
set -e

echo "=== Smart City SOA — Teardown ==="

for INSTANCE in smartcity-services wazuh; do
    if incus info "$INSTANCE" &>/dev/null; then
        echo "[*] Deleting $INSTANCE"
        incus delete "$INSTANCE" --force
    else
        echo "[~] $INSTANCE not found, skipping"
    fi
done

SHARED_LOGS="$HOME/smartcity-shared-logs"
if [ -d "$SHARED_LOGS" ]; then
    echo "[*] Removing shared logs at $SHARED_LOGS"
    rm -rf "$SHARED_LOGS"
else
    echo "[~] $SHARED_LOGS not found, skipping"
fi

echo "=== Teardown complete. Run: bash scripts/setup_incus.sh ==="
