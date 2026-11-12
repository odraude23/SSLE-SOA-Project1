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
SHARED_LOGS="$HOME/smartcity-shared-logs"

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
    incus launch images:ubuntu/22.04 smartcity-services \
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

fi

# ── wazuh container ─────────────────────────────────────────────────────────
if incus info wazuh &>/dev/null; then
    echo "[~] wazuh already exists, skipping creation"
else
    echo "[*] Launching wazuh container (Ubuntu 22.04)"
    incus launch images:ubuntu/22.04 wazuh \
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

    echo "[*] Deploying Wazuh custom rules and active response"
    incus file push "$PROJECT_DIR/monitoring/wazuh/local_rules.xml" \
        wazuh/var/ossec/etc/rules/local_rules.xml
    incus file push "$PROJECT_DIR/monitoring/wazuh/block-threat.sh" \
        wazuh/var/ossec/active-response/bin/block-threat.sh
    incus exec wazuh -- chmod +x /var/ossec/active-response/bin/block-threat.sh

    echo "[*] Injecting localfile monitors and active response into default ossec.conf"
    incus exec wazuh -- python3 -c "
additions = '''
  <!-- SmartCity service logs (bind-mounted via shared Incus disk at /var/log/smartcity) -->
  <localfile><log_format>json</log_format><location>/var/log/smartcity/registry/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/ingestion/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/storage/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/analytics/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/ops-portal/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/alert-service/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/zone-aggregator-north/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/zone-aggregator-center/access.log</location></localfile>
  <localfile><log_format>json</log_format><location>/var/log/smartcity/zone-aggregator-south/access.log</location></localfile>
  <localfile><log_format>syslog</log_format><location>/var/log/smartcity/mail/mail.log</location></localfile>
  <!-- Active response: block IPs triggering DDoS/APT/spam rules -->
  <command><name>block-threat</name><executable>block-threat.sh</executable><timeout_allowed>yes</timeout_allowed></command>
  <active-response><command>block-threat</command><location>local</location><rules_id>100002,100101,100201,100301,100303</rules_id><timeout>300</timeout></active-response>
'''
path = '/var/ossec/etc/ossec.conf'
cfg = open(path).read()
if 'SmartCity service logs' not in cfg:
    cfg = cfg.replace('</ossec_config>', additions + '</ossec_config>')
    open(path, 'w').write(cfg)
    print('Injected.')
else:
    print('Already injected, skipping.')
"

    incus exec wazuh -- systemctl restart wazuh-manager
    incus exec wazuh -- systemctl is-active wazuh-manager
fi

# ── Resolve IPs and Wazuh password ──────────────────────────────────────────
SC_IP=$(incus info smartcity-services 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info smartcity-services 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "pending")
WZ_IP=$(incus info wazuh 2>/dev/null | grep -oP 'eth0.*?\K[\d.]+' | head -1 || \
        incus info wazuh 2>/dev/null | grep -oP 'enp.*?\K[\d.]+' | head -1 || echo "pending")
WAZUH_PASS=$(incus exec wazuh -- grep -A2 "^    User: wazuh$" /root/wazuh-install.log 2>/dev/null | grep "Password:" | awk '{print $2}')
if [ -z "$WAZUH_PASS" ]; then
    WAZUH_PASS=$(incus exec wazuh -- grep -A2 "User: admin" /root/wazuh-install.log 2>/dev/null | grep "Password:" | awk '{print $2}')
fi
if [ -z "$WAZUH_PASS" ]; then
    WAZUH_PASS="CHANGE_ME — check: incus exec wazuh -- cat /root/wazuh-install.log"
fi

# ── Generate .env from .env.example ─────────────────────────────────────────
INTERNAL_TOKEN=$(openssl rand -hex 32)
echo "[*] Generating .env (WAZUH_HOST=$WZ_IP)"
cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
sed -i "s|^INTERNAL_TOKEN=.*|INTERNAL_TOKEN=$INTERNAL_TOKEN|" "$PROJECT_DIR/.env"
sed -i "s|^WAZUH_HOST=.*|WAZUH_HOST=$WZ_IP|" "$PROJECT_DIR/.env"
sed -i "s|^WAZUH_PASS=.*|WAZUH_PASS=$WAZUH_PASS|" "$PROJECT_DIR/.env"

# ── Copy project files into smartcity-services ──────────────────────────────
if incus info smartcity-services &>/dev/null && \
   ! incus exec smartcity-services -- test -d /home/ubuntu/smartcity/services 2>/dev/null; then
    echo "[*] Copying project files into smartcity-services"
    incus exec smartcity-services -- mkdir -p /home/ubuntu/smartcity
    tar -C "$PROJECT_DIR" -czf - . | incus exec smartcity-services -- bash -c "tar -xzf - -C /home/ubuntu/smartcity/"
    incus exec smartcity-services -- chown -R ubuntu:ubuntu /home/ubuntu/smartcity 2>/dev/null || true
    incus file push "$PROJECT_DIR/.env" smartcity-services/home/ubuntu/smartcity/.env
fi

# ── Print summary ────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo "  smartcity-services IP : $SC_IP"
echo "  wazuh IP              : $WZ_IP"
echo "  WAZUH_PASS            : $WAZUH_PASS"
echo "  .env written to       : $PROJECT_DIR/.env"
echo ""
echo "Next step: bash scripts/run_all.sh"
