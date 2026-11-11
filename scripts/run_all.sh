#!/bin/bash
# Start all services via docker compose inside the smartcity-services Incus VM.
set -e

echo "=== Smart City SOA — Starting Services ==="

# Update WAZUH_HOST in .env inside the VM
WZ_IP=$(incus info wazuh 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info wazuh 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "")

if [ -n "$WZ_IP" ]; then
    echo "[*] Detected wazuh IP: $WZ_IP — updating .env"
    incus exec smartcity-services -- bash -c "
        cd /home/ubuntu/smartcity
        sed -i 's|WAZUH_HOST=.*|WAZUH_HOST=$WZ_IP|' .env
    "
else
    echo "[!] Could not detect wazuh IP. Update WAZUH_HOST in .env manually."
fi

echo "[*] Running docker compose up --build"
incus exec smartcity-services -- bash -c "
    cd /home/ubuntu/smartcity
    docker compose up --build -d
"

# Get VM IP for user-facing URLs
SC_IP=$(incus info smartcity-services 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info smartcity-services 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "smartcity-services")

echo ""
echo "=== All services running ==="
echo "  Ops Portal   : http://$SC_IP:5600"
echo "  Grafana      : http://$SC_IP:3000  (admin / admin)"
echo "  Prometheus   : http://$SC_IP:9090"
echo "  Registry API : http://$SC_IP:5050/services"
echo ""
echo "Check status:  incus exec smartcity-services -- docker compose ps"
echo "View logs:     incus exec smartcity-services -- docker compose logs -f <service>"
