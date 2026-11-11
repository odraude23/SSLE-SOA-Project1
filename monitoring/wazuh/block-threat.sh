#!/bin/bash
# Wazuh active response: block attacker IP via iptables
# Called by Wazuh with args: action add/delete, user, ip, alert_id, rule_id
#
# Wazuh passes: $1=action, $2=user, $3=ip, $4=alert_id, $5=rule_id
# (For newer Wazuh 4.x the JSON input is on stdin; we support both)

ACTION=$1
USER=$2
IP=$3
ALERT_ID=$4
RULE_ID=$5
TIMEOUT=300

LOGFILE="/var/log/wazuh-active-response.log"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) action=$ACTION ip=$IP rule_id=$RULE_ID alert_id=$ALERT_ID msg=$1" >> "$LOGFILE"
}

if [ -z "$IP" ] || [ "$IP" = "-" ]; then
    log "no_ip_skipped"
    exit 0
fi

case "$ACTION" in
    add)
        iptables -I INPUT -s "$IP" -j DROP
        log "blocked"
        # Auto-unblock after timeout
        (sleep "$TIMEOUT"; iptables -D INPUT -s "$IP" -j DROP; echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) action=unblocked ip=$IP" >> "$LOGFILE") &
        ;;
    delete)
        iptables -D INPUT -s "$IP" -j DROP 2>/dev/null || true
        log "unblocked"
        ;;
    *)
        log "unknown_action"
        exit 1
        ;;
esac

exit 0
