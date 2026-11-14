#!/bin/bash
# Wazuh 4.x active response: delegate IP blocking to threat-blocker service.
#
# Wazuh 4.x sends alert data as a JSON object on stdin (not positional args).
# Format: {"version":1,"command":"add","parameters":{"alert":{...}}}
#
# threat-blocker runs with network_mode:host inside smartcity-services,
# so its iptables commands modify the DOCKER-USER chain on the Docker host.

CONF="/var/ossec/etc/blocker.conf"
LOGFILE="/var/log/wazuh-active-response.log"

BLOCKER_URL="http://localhost:9200"
BLOCKER_TOKEN="changeme"
if [ -f "$CONF" ]; then
    # shellcheck source=/dev/null
    source "$CONF"
fi

# Read full stdin into a temp file (JSON can be multi-line)
INPUT_FILE=$(mktemp)
cat > "$INPUT_FILE"

# Log raw input for debugging (truncated)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) raw=$(head -c 300 "$INPUT_FILE")" >> "$LOGFILE"

# Parse command, IP and rule_id in one Python call
eval "$(python3 -c "
import json, sys
try:
    d = json.load(open('$INPUT_FILE'))
    alert = d.get('parameters', {}).get('alert', {})
    data  = alert.get('data', {})
    ip    = data.get('srcip') or data.get('client_ip', '')
    cmd   = d.get('command', '')
    rule  = alert.get('rule', {}).get('id', '')
    print(f'ACTION={cmd}')
    print(f'IP={ip}')
    print(f'RULE_ID={rule}')
except Exception as e:
    print(f'ACTION=')
    print(f'IP=')
    print(f'RULE_ID=')
    import sys; print(f'PARSE_ERR={e}', file=sys.stderr)
" 2>> "$LOGFILE")"

rm -f "$INPUT_FILE"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) action=$ACTION ip=$IP rule_id=$RULE_ID msg=$1" >> "$LOGFILE"
}

if [ -z "$IP" ] || [ "$IP" = "-" ]; then
    log "no_ip_skipped"
    exit 0
fi

case "$ACTION" in
    add)
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "$BLOCKER_URL/block" \
            -H "x-internal-token: $BLOCKER_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"ip\": \"$IP\", \"duration\": 300}")
        if [ "$STATUS" = "200" ]; then
            log "block_requested_ok"
        else
            log "block_request_failed http=$STATUS"
        fi
        ;;
    delete)
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            -X DELETE "$BLOCKER_URL/block/$IP" \
            -H "x-internal-token: $BLOCKER_TOKEN")
        if [ "$STATUS" = "200" ]; then
            log "unblock_requested_ok"
        else
            log "unblock_request_failed http=$STATUS"
        fi
        ;;
    *)
        log "unknown_action=$ACTION"
        exit 1
        ;;
esac

exit 0
