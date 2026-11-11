#!/bin/bash
# Stop all services (keeps containers and data intact for next run_all.sh).
# Use --volumes to also wipe SQLite data.
set -e

echo "=== Smart City SOA — Stopping Services ==="
incus exec smartcity-services -- bash -c "cd /home/ubuntu/smartcity && docker compose down"
echo "[+] Done. Data volumes preserved."
echo "    To also delete data: incus exec smartcity-services -- bash -c 'cd /home/ubuntu/smartcity && docker compose down -v'"
