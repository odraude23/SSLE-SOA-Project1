#!/bin/bash
# Deletes Wazuh alert indices from OpenSearch.
# Wazuh container must be running.
set -e

echo "=== Clearing Wazuh indices ==="

STATE=$(incus info wazuh 2>/dev/null | grep -oP 'Status: \K\w+' || echo "MISSING")
if [ "$STATE" = "MISSING" ]; then
    echo "[!] wazuh container not found — run setup_incus.sh first"
    exit 1
elif [ "$STATE" != "RUNNING" ]; then
    echo "[*] Starting wazuh container..."
    incus start wazuh
    sleep 10
else
    echo "[~] wazuh already running"
fi

ADMIN_PASS=$(incus exec wazuh -- grep -A2 "User: admin" /root/wazuh-install.log 2>/dev/null \
             | grep "Password:" | awk '{print $2}' || echo "")

if [ -z "$ADMIN_PASS" ]; then
    echo "[!] Could not read admin password from install log"
    exit 1
fi

incus exec wazuh -- bash -c "
    for i in \$(seq 1 20); do
        curl -sk -o /dev/null 'https://localhost:9200' -u 'admin:$ADMIN_PASS' && break
        echo '  waiting for indexer... attempt '\$i'/20'
        sleep 5
    done
    curl -sk -X DELETE 'https://localhost:9200/wazuh-alerts-*'   -u 'admin:$ADMIN_PASS' | python3 -m json.tool 2>/dev/null || true
    curl -sk -X DELETE 'https://localhost:9200/wazuh-archives-*' -u 'admin:$ADMIN_PASS' | python3 -m json.tool 2>/dev/null || true
"

echo "[+] Done"
