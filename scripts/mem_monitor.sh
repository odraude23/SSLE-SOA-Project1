#!/bin/bash
# Memory monitor daemon — appends a snapshot every 30s to a log file.
# Run with: nohup bash scripts/mem_monitor.sh &
# Stop with: kill $(cat ~/mem_monitor.pid)

LOG="${1:-$HOME/mem_monitor.log}"
PID_FILE="$HOME/mem_monitor.pid"
INTERVAL=30

echo $$ > "$PID_FILE"
echo "[mem_monitor] Started PID=$$, logging to $LOG every ${INTERVAL}s"

while true; do
    TS=$(date '+%Y-%m-%d %H:%M:%S')
    {
        echo "════════════════════════════════════════════════════"
        echo "TIMESTAMP: $TS"
        echo ""

        echo "── VM Memory ──────────────────────────────────────"
        free -h
        echo ""

        echo "── Top 12 processes by RSS ─────────────────────────"
        ps aux --sort=-%mem | head -13
        echo ""

        echo "── Incus containers ────────────────────────────────"
        incus list -f compact 2>/dev/null || echo "(incus not available)"
        echo ""

        echo "── Docker container memory ─────────────────────────"
        incus exec smartcity-services -- \
            docker stats --no-stream --format \
            "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}" \
            2>/dev/null || echo "(smartcity-services not running)"
        echo ""

        echo "── Wazuh top processes ─────────────────────────────"
        incus exec wazuh -- \
            ps aux --sort=-%mem 2>/dev/null | head -8 \
            || echo "(wazuh container not running)"
        echo ""

    } >> "$LOG"

    # Force flush to disk — critical so last entry survives a freeze
    sync

    sleep "$INTERVAL"
done
