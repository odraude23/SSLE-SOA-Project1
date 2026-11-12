#!/bin/bash
# Stop all services. Data and volumes are preserved — use reset_all.sh for a clean slate.
set -e

echo "=== Smart City SOA — Stopping Services ==="

incus exec smartcity-services -- bash -c "cd /home/ubuntu/smartcity && docker compose down" 2>/dev/null || true

echo "[*] Stopping wazuh container"
incus stop wazuh 2>/dev/null || true

echo "[+] Done. Run bash scripts/run_all.sh to start again."
