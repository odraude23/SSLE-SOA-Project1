#!/bin/bash
# Wazuh active response: delegate IP blocking to threat-blocker service.
#
# threat-blocker runs with network_mode:host inside the smartcity-services
# Incus container, so its iptables commands modify the Docker host's
# DOCKER-USER chain — the correct place to block traffic to any container.
#
# Setup (run once after deployment):
#   echo "BLOCKER_URL=http://<smartcity-services-ip>:9200" \
#     > /var/ossec/etc/blocker.conf
#   echo "BLOCKER_TOKEN=<INTERNAL_TOKEN value>" \
#     >> /var/ossec/etc/blocker.conf
#
# Wazuh passes: $1=action  $2=user  $3=ip  $4=alert_id  $5=rule_id

ACTION=$1
USER=$2
IP=$3
ALERT_ID=$4
RULE_ID=$5

CONF="/var/ossec/etc/blocker.conf"
LOGFILE="/var/log/wazuh-active-response.log"

# Source config file for BLOCKER_URL and BLOCKER_TOKEN
BLOCKER_URL="http://localhost:9200"
BLOCKER_TOKEN="changeme"
if [ -f "$CONF" ]; then
    # shellcheck source=/dev/null
    source "$CONF"
fi

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) action=$ACTION ip=$IP rule_id=$RULE_ID alert_id=$ALERT_ID msg=$1" >> "$LOGFILE"
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
        log "unknown_action"
        exit 1
        ;;
esac

exit 0
