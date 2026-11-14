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
WAZUH_ALERTS="$HOME/wazuh-alerts-shared"

echo "=== Smart City SOA — Incus Setup ==="
echo "Project: $PROJECT_DIR"

# ── Host kernel prerequisites ────────────────────────────────────────────────
# br_netfilter is required for Docker to run with userland-proxy:false.
# It must be loaded on the Incus host (this machine), not inside the container.
echo "[*] Loading br_netfilter kernel module"
if ! lsmod | grep -q br_netfilter; then
    sudo modprobe br_netfilter
fi
sudo sysctl -qw net.bridge.bridge-nf-call-iptables=1
sudo sysctl -qw net.bridge.bridge-nf-call-ip6tables=1
# Persist across reboots
echo 'br_netfilter' | sudo tee /etc/modules-load.d/br_netfilter.conf > /dev/null
printf 'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\n' \
    | sudo tee /etc/sysctl.d/99-br-netfilter.conf > /dev/null

# ── Shared directories on the Incus host ────────────────────────────────────
echo "[*] Creating shared directories"
mkdir -p "$SHARED_LOGS"/{registry,ingestion,storage,analytics,ops-portal,alert-service,zone-aggregator-north,zone-aggregator-center,zone-aggregator-south,mail,threat-blocker}
chmod -R 777 "$SHARED_LOGS"
mkdir -p "$WAZUH_ALERTS"
chmod 777 "$WAZUH_ALERTS"

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
    incus config device add smartcity-services wazuh-alerts disk \
        source="$WAZUH_ALERTS" \
        path=/home/ubuntu/wazuh-alerts

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
        # Write daemon.json BEFORE installing Docker so it starts with this config.
        # userland-proxy:false makes containers see the real source IP for published ports
        # instead of 172.17.0.1 (the Docker bridge gateway from the userland proxy).
        mkdir -p /etc/docker
        printf '{\"userland-proxy\": false}\n' > /etc/docker/daemon.json
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

    echo "[*] Mounting wazuh alerts directory to host (for wazuh-exporter)"
    incus config device add wazuh wazuh-alerts disk \
        source="$WAZUH_ALERTS" \
        path=/var/ossec/logs/alerts

    incus exec wazuh -- systemctl restart wazuh-manager
    incus exec wazuh -- systemctl is-active wazuh-manager
fi

# ── Resolve IPs and Wazuh password ──────────────────────────────────────────
# smartcity-services has two IPs (eth0 + docker0) — filter for eth0 only
SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1 || echo "pending")
WZ_IP=$(incus list wazuh -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1 || echo "pending")
WAZUH_PASS=$(incus exec wazuh -- bash -c "
    # Extract the passwords archive if not already done
    [ -d /tmp/wazuh-install-files ] || \
        tar xf /root/wazuh-install-files.tar -C /tmp 2>/dev/null || true
    python3 - <<'PYEOF'
import re, sys
try:
    txt = open('/tmp/wazuh-install-files/wazuh-passwords.txt').read()
except FileNotFoundError:
    sys.exit(1)
# Format 1 (Wazuh 4.7+): username: 'wazuh'\n  password: 'PASS'
m = re.search(r\"username:\\s*'wazuh'[^\\n]*\\n\\s*password:\\s*'([^']+)'\", txt)
if not m:
    # Format 2: The password for user wazuh is 'PASS' or \"PASS\"
    m = re.search(r\"user(?:name)?[: ]+['\\\"]?wazuh['\\\"]?[^\\n]*\\n.*?password[: ]+['\\\"]([^'\\\"\\n]+)\", txt, re.DOTALL)
if not m:
    # Format 3: wazuh_api_password or wazuh: PASS on same/next line
    m = re.search(r\"(?:wazuh[_-]api[_-]password|'wazuh')[^\\n]*?[: ]+['\\\"]?([A-Za-z0-9!@#\$%^&*_+=./-]{8,})['\\\"]?\", txt)
if m:
    print(m.group(1).strip())
else:
    sys.exit(1)
PYEOF
" 2>/dev/null || echo "")
if [ -z "$WAZUH_PASS" ]; then
    WAZUH_PASS="CHANGE_ME"
    echo "[!] Could not auto-extract Wazuh password."
    echo "    Run: incus exec wazuh -- cat /tmp/wazuh-install-files/wazuh-passwords.txt"
    echo "    Then update WAZUH_PASS in .env manually."
fi

# ── Generate .env from .env.example ─────────────────────────────────────────
INTERNAL_TOKEN=$(openssl rand -hex 32)
echo "[*] Generating .env (WAZUH_HOST=$WZ_IP)"
cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
sed -i "s|^INTERNAL_TOKEN=.*|INTERNAL_TOKEN=$INTERNAL_TOKEN|" "$PROJECT_DIR/.env"
sed -i "s|^WAZUH_HOST=.*|WAZUH_HOST=$WZ_IP|" "$PROJECT_DIR/.env"
sed -i "s|^WAZUH_PASS=.*|WAZUH_PASS=$WAZUH_PASS|" "$PROJECT_DIR/.env"
sed -i "s|^WAZUH_ALERTS_PATH=.*|WAZUH_ALERTS_PATH=/home/ubuntu/wazuh-alerts|" "$PROJECT_DIR/.env"

# ── Configure threat-blocker endpoint on Wazuh ──────────────────────────────
# block-threat.sh reads this file to know where to send block requests.
echo "[*] Writing blocker.conf on wazuh container"
incus exec wazuh -- bash -c "
    echo 'BLOCKER_URL=http://$SC_IP:9200' > /var/ossec/etc/blocker.conf
    echo 'BLOCKER_TOKEN=$INTERNAL_TOKEN'  >> /var/ossec/etc/blocker.conf
    chmod 600 /var/ossec/etc/blocker.conf
"

# ── Copy project files into smartcity-services ──────────────────────────────
if incus info smartcity-services &>/dev/null && \
   ! incus exec smartcity-services -- test -d /home/ubuntu/smartcity/services 2>/dev/null; then
    echo "[*] Copying project files into smartcity-services"
    incus exec smartcity-services -- mkdir -p /home/ubuntu/smartcity
    tar -C "$PROJECT_DIR" -czf - . | incus exec smartcity-services -- bash -c "tar -xzf - -C /home/ubuntu/smartcity/"
    # Chown everything except the bind-mounted logs directory (owned by the Incus host).
    incus exec smartcity-services -- bash -c "
        chown ubuntu:ubuntu /home/ubuntu/smartcity
        find /home/ubuntu/smartcity -mindepth 1 \
            -not -path '/home/ubuntu/smartcity/logs*' \
            -exec chown ubuntu:ubuntu {} +
    "
    incus file push "$PROJECT_DIR/.env" smartcity-services/home/ubuntu/smartcity/.env
    # Postfix inside the mail-server container writes as the 'postfix' user.
    # The mailbox directory must be world-writable so it can create the operator mailbox.
    incus exec smartcity-services -- chmod 777 /home/ubuntu/smartcity/mailbox
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
