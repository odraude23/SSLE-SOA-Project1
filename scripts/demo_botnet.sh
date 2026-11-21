#!/bin/bash
# Demo script — Threat 4: Botnet DDoS
#
# Spawns N Incus containers (clones of the attacker), each flooding the
# ops-portal from its own Incus IP.  Every bot independently triggers
# Wazuh rule 100002 (50+ req/10s).  Rule 100003 fires when 3+ distinct
# source IPs each exceed the DDoS threshold within 2 minutes.
#
# Usage:
#   bash scripts/demo_botnet.sh [N]      (default N=3)

set -euo pipefail

BOT_COUNT="${1:-3}"
ATTACK_DURATION=90
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── Detect smartcity-services IP ─────────────────────────────────────────────
SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)

if [ -z "$SC_IP" ]; then
    echo "[!] Could not resolve smartcity-services IP. Is the container running?"
    exit 1
fi

TARGET="http://$SC_IP:5600"

echo "=================================================="
echo " Threat 4 — Botnet DDoS"
echo "=================================================="
echo "  Bots     : $BOT_COUNT (clones of attacker container)"
echo "  Target   : $TARGET"
echo "  Duration : ${ATTACK_DURATION}s per bot"
echo ""
echo "  Watch in Grafana (Threat 1 — DDoS row):"
echo "    Currently Blocked IPs  → $BOT_COUNT IPs appear one by one"
echo "    Wazuh Alerts           → rule 100002 fires per bot"
echo "                             rule 100003 fires (Botnet confirmed)"
echo "=================================================="
echo ""

# ── Spawn bot containers ──────────────────────────────────────────────────────
BOT_NAMES=()
for i in $(seq 1 "$BOT_COUNT"); do
    NAME="bot-${i}"
    BOT_NAMES+=("$NAME")
    echo "[*] Creating $NAME (copy of attacker)..."
    incus copy attacker "$NAME"
    incus start "$NAME"
done

echo ""
echo "[*] Waiting for bots to get network addresses..."
sleep 6

# Push botnet worker script into each bot and show its IP
echo ""
for NAME in "${BOT_NAMES[@]}"; do
    BOT_IP=$(incus list "$NAME" -f csv -c 4 2>/dev/null \
        | grep eth0 | grep -oP '[\d.]+' | head -1)
    incus file push "$REPO_ROOT/poc/botnet_attack.py" \
        "$NAME/root/poc/botnet_attack.py"
    echo "  $NAME → ${BOT_IP:-<pending>}"
done

# ── Coordinated flood ─────────────────────────────────────────────────────────
echo ""
echo "[*] Launching coordinated flood from $BOT_COUNT bots..."
PIDS=()
for NAME in "${BOT_NAMES[@]}"; do
    incus exec "$NAME" -- python3 /root/poc/botnet_attack.py \
        --target   "$TARGET" \
        --threads  20 \
        --duration "$ATTACK_DURATION" &
    PIDS+=($!)
    echo "  [+] $NAME launched (PID $!)"
done

echo ""
echo "[*] All bots running in parallel. Waiting for attack to complete..."
for PID in "${PIDS[@]}"; do
    wait "$PID" 2>/dev/null || true
done

# ── Results ───────────────────────────────────────────────────────────────────
echo ""
echo "[+] Attack complete."
echo "[+] Expected Wazuh alerts:"
echo "    rule 100002 — fired once per bot IP (DDoS threshold exceeded)"
echo "    rule 100003 — fired when 3rd distinct IP triggered 100002 (Botnet confirmed)"
echo ""

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo "[*] Deleting bot containers..."
for NAME in "${BOT_NAMES[@]}"; do
    incus stop   "$NAME" --force  2>/dev/null || true
    incus delete "$NAME"          2>/dev/null || true
    echo "  [-] $NAME removed"
done

echo ""
echo "[*] Clearing iptables DROP rules..."
bash "$REPO_ROOT/scripts/unblock_ips.sh"

echo ""
echo "[+] Done."
