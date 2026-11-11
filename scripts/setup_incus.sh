#!/bin/bash
# One-time setup: creates two Incus instances and wires them together.
#
#   smartcity-services  — Ubuntu 22.04 VM running Docker Compose
#   wazuh               — Ubuntu 22.04 container running Wazuh all-in-one
#
# After this script finishes:
#   1. Edit .env and fill in WAZUH_HOST (printed at the end)
#   2. Run: bash scripts/run_all.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_LOGS="/shared/smartcity-logs"

echo "=== Smart City SOA — Incus Setup ==="
echo "Project: $PROJECT_DIR"

# ── Shared log directory on the Incus host ──────────────────────────────────
echo "[*] Creating shared log directory at $SHARED_LOGS"
mkdir -p "$SHARED_LOGS"

# ── smartcity-services VM ───────────────────────────────────────────────────
if incus info smartcity-services &>/dev/null; then
    echo "[~] smartcity-services already exists, skipping creation"
else
    echo "[*] Launching smartcity-services container (Ubuntu 22.04, nesting enabled for Docker)"
    incus launch ubuntu:22.04 smartcity-services \
        --config limits.cpu=2 \
        --config limits.memory=3GiB \
        --config security.nesting=true

    echo "[*] Waiting for container to boot..."
    sleep 10

    echo "[*] Mounting shared logs into VM"
    incus config device add smartcity-services shared-logs disk \
        source="$SHARED_LOGS" \
        path=/home/ubuntu/smartcity/logs

    echo "[*] Installing Docker in VM"
    incus exec smartcity-services -- bash -c "
        apt-get update -q
        apt-get install -y -q ca-certificates curl gnupg lsb-release
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
        echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
            https://download.docker.com/linux/ubuntu \$(lsb_release -cs) stable\" \
            | tee /etc/apt/sources.list.d/docker.list
        apt-get update -q
        apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
        usermod -aG docker ubuntu
    "

    echo "[*] Copying project files to VM"
    incus exec smartcity-services -- mkdir -p /home/ubuntu/smartcity
    incus file push --recursive "$PROJECT_DIR/" smartcity-services/home/ubuntu/smartcity/
    incus exec smartcity-services -- chown -R ubuntu:ubuntu /home/ubuntu/smartcity

    echo "[*] Copying .env"
    if [ -f "$PROJECT_DIR/.env" ]; then
        incus file push "$PROJECT_DIR/.env" smartcity-services/home/ubuntu/smartcity/.env
    else
        incus file push "$PROJECT_DIR/.env.example" smartcity-services/home/ubuntu/smartcity/.env
        echo "[!] .env not found — copied .env.example. Update WAZUH_HOST before run_all.sh"
    fi
fi

# ── wazuh container ─────────────────────────────────────────────────────────
if incus info wazuh &>/dev/null; then
    echo "[~] wazuh already exists, skipping creation"
else
    echo "[*] Launching wazuh container (Ubuntu 22.04)"
    incus launch ubuntu:22.04 wazuh \
        --config limits.cpu=2 \
        --config limits.memory=4GiB

    echo "[*] Waiting for container to boot..."
    sleep 15

    echo "[*] Mounting shared logs into wazuh (read-write so Wazuh can monitor them)"
    incus config device add wazuh shared-logs disk \
        source="$SHARED_LOGS" \
        path=/var/log/smartcity

    echo "[*] Installing Wazuh all-in-one (this takes ~5 minutes)..."
    incus exec wazuh -- bash -c "
        apt-get update -q
        apt-get install -y -q curl
        curl -sO https://packages.wazuh.com/4.9/wazuh-install.sh
        bash wazuh-install.sh -a --ignore-check 2>&1 | tee /root/wazuh-install.log
    "

    echo "[*] Resetting Wazuh API password to known value (Wazuh1234!)..."
    incus exec wazuh -- bash -c "
        # Wait for indexer to be ready
        sleep 10
        /usr/share/wazuh-indexer/plugins/opensearch-security/tools/wazuh-passwords-tool.sh \
            -u wazuh -p 'Wazuh1234!' 2>&1 | tail -5
    " || echo "[!] Password reset failed — check /root/wazuh-install.log for the generated password"

    echo "[*] Deploying Wazuh config"
    incus file push "$PROJECT_DIR/monitoring/wazuh/ossec.conf" \
        wazuh/var/ossec/etc/ossec.conf
    incus file push "$PROJECT_DIR/monitoring/wazuh/local_rules.xml" \
        wazuh/var/ossec/etc/rules/local_rules.xml
    incus file push "$PROJECT_DIR/monitoring/wazuh/block-threat.sh" \
        wazuh/var/ossec/active-response/bin/block-threat.sh
    incus exec wazuh -- chmod +x /var/ossec/active-response/bin/block-threat.sh
    incus exec wazuh -- systemctl restart wazuh-manager
fi

# ── Print summary ────────────────────────────────────────────────────────────
SC_IP=$(incus info smartcity-services 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info smartcity-services 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "pending")
WZ_IP=$(incus info wazuh 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info wazuh 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "pending")

echo ""
echo "=== Setup complete ==="
echo "  smartcity-services IP : $SC_IP"
echo "  wazuh IP              : $WZ_IP"
echo ""
echo "Next steps:"
echo "  1. Edit .env — set WAZUH_HOST=$WZ_IP"
echo "     (run: incus exec smartcity-services -- nano /home/ubuntu/smartcity/.env)"
echo "  2. bash scripts/run_all.sh"
