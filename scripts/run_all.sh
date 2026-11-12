#!/bin/bash
# Start all services: brings up Wazuh, then Docker Compose inside smartcity-services.
set -e

echo "=== Smart City SOA — Starting Services ==="

# ── Stop Wazuh before build (avoid noisy build logs filling alerts storage) ──
if incus info wazuh &>/dev/null; then
    STATE=$(incus info wazuh | grep -oP 'Status: \K\w+')
    if [ "$STATE" = "RUNNING" ]; then
        echo "[*] Stopping wazuh container during build..."
        incus stop wazuh
    fi
else
    echo "[!] wazuh container not found — run setup_incus.sh first"
    exit 1
fi

# ── Start Docker Compose ─────────────────────────────────────────────────────
echo "[*] Running docker compose up --build"
incus exec smartcity-services -- bash -c "
    cd /home/ubuntu/smartcity
    docker compose up --build -d
"

# ── Start Wazuh after build ──────────────────────────────────────────────────
echo "[*] Starting wazuh container..."
incus start wazuh
sleep 5

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1 || echo "smartcity-services")

echo ""
echo "=== All services running ==="
echo "  Ops Portal   : http://$SC_IP:5600"
echo "  Grafana      : http://$SC_IP:3000  (admin / admin)"
echo "  Prometheus   : http://$SC_IP:9090"
echo "  Registry API : http://$SC_IP:5050/services"
echo ""
echo "Check status:  incus exec smartcity-services -- bash -c 'cd /home/ubuntu/smartcity && docker compose ps'"
echo "View logs:     incus exec smartcity-services -- bash -c 'cd /home/ubuntu/smartcity && docker compose logs -f <service>'"
