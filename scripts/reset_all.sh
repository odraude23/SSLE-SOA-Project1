#!/bin/bash
# Full reset: wipes all experiment data (Docker volumes, service logs, Wazuh indices).
# Use this between demo runs. Wazuh container must be reachable.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_LOGS="$HOME/smartcity-shared-logs"

echo "=== Smart City SOA — Full Reset ==="

# ── Ensure wazuh container is running (needed for index deletion) ────────────
STATE=$(incus info wazuh 2>/dev/null | grep -oP 'Status: \K\w+' || echo "MISSING")
if [ "$STATE" = "MISSING" ]; then
    echo "[!] wazuh container not found — run setup_incus.sh first"
    exit 1
elif [ "$STATE" != "RUNNING" ]; then
    echo "[*] Starting wazuh container for cleanup..."
    incus start wazuh
    sleep 10
else
    echo "[~] wazuh already running"
fi

# ── Delete Wazuh indices via OpenSearch REST API ─────────────────────────────
echo "[*] Clearing Wazuh indices..."
ADMIN_PASS=$(incus exec wazuh -- grep -A2 "User: admin" /root/wazuh-install.log 2>/dev/null \
             | grep "Password:" | awk '{print $2}' || echo "")

if [ -z "$ADMIN_PASS" ]; then
    echo "[!] Could not read admin password — skipping index cleanup"
else
    incus exec wazuh -- bash -c "
        for i in \$(seq 1 20); do
            curl -sk -o /dev/null 'https://localhost:9200' -u 'admin:$ADMIN_PASS' && break
            echo '  waiting for indexer... attempt '\$i'/20'
            sleep 5
        done
        curl -sk -X DELETE 'https://localhost:9200/wazuh-alerts-*'   -u 'admin:$ADMIN_PASS' | python3 -m json.tool 2>/dev/null || true
        curl -sk -X DELETE 'https://localhost:9200/wazuh-archives-*' -u 'admin:$ADMIN_PASS' | python3 -m json.tool 2>/dev/null || true
    "
    echo "[+] Wazuh indices cleared"
fi

# ── Stop Docker services and wipe volumes (SQLite + all named volumes) ────────
echo "[*] Stopping Docker services and wiping volumes..."
incus exec smartcity-services -- bash -c \
    "cd /home/ubuntu/smartcity && docker compose down -v" 2>/dev/null || true

# ── Clear shared service logs ─────────────────────────────────────────────────
echo "[*] Clearing shared service logs at $SHARED_LOGS"
find "$SHARED_LOGS" -type f -delete 2>/dev/null || true

# ── Stop wazuh container ──────────────────────────────────────────────────────
echo "[*] Stopping wazuh container"
incus stop wazuh 2>/dev/null || true

echo ""
echo "=== Reset complete. Run: bash scripts/run_all.sh ==="
