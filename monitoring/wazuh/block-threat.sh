#!/bin/bash
# Wazuh 4.x active response: delegate IP blocking to threat-blocker service.
#
# Protocol: Wazuh 4.x sends one JSON line on stdin per invocation and waits for
# a response on stdout before proceeding. Use `read` (not `cat`) — `cat` blocks
# until stdin EOF, but execd keeps stdin open waiting for stdout: deadlock.
# Fix: read exactly one line, echo it back immediately, then act.

CONF="/var/ossec/etc/blocker.conf"
LOGFILE="/var/log/wazuh-active-response.log"
BLOCKER_URL="http://localhost:9200"
BLOCKER_TOKEN="changeme"
if [ -f "$CONF" ]; then
    # shellcheck source=/dev/null
    source "$CONF"
fi

# Read exactly one line from stdin (the Wazuh alert JSON)
read -r INPUT_JSON

# Respond to execd immediately — it is waiting on stdout before it proceeds
echo "$INPUT_JSON"

# Log raw input for debugging (truncated to 200 chars)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) raw=$(echo "$INPUT_JSON" | cut -c1-200)" >> "$LOGFILE"

# Write JSON to a temp file so Python can parse it safely
INPUT_FILE=$(mktemp)
printf '%s\n' "$INPUT_JSON" > "$INPUT_FILE"

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
    print('ACTION=')
    print('IP=')
    print('RULE_ID=')
    sys.stderr.write(f'PARSE_ERR={e}\n')
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
            -d "{\"ip\": \"$IP\", \"duration\": 300, \"rule_id\": \"$RULE_ID\"}")
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
        ;;
esac

exit 0
