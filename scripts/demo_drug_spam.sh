#!/usr/bin/env bash
# demo_drug_spam.sh — Threat 3 content-based variant: pharmaceutical spam
#
# Sends drug-content emails directly via SMTP.
# SpamAssassin scores each ~14 stars → Postfix DISCARD.
# Result: zero emails in operator mailbox.

set -euo pipefail

SC_IP="$(incus list smartcity-services --format csv -c 4 2>/dev/null \
    | grep eth0 | grep -oP '[\d.]+' | head -1)"
if [ -z "$SC_IP" ]; then
    echo "[!] Could not detect smartcity-services IP"
    exit 1
fi

TARGET="${SC_IP}:25"
COUNT="${1:-10}"

echo "=================================================="
echo " Threat 3 — Drug Spam (SpamAssassin Content Filter)"
echo "=================================================="
echo " Target mail server : $TARGET"
echo " Emails to send     : $COUNT"
echo ""
echo " Grafana: Threat 3 — Drug Spam row (Drug Spam Blocked, Received vs Discarded, Emails Delivered)"
echo " Verify via: cat logs/mail/mail.log | grep discard"
echo " Mailbox:    ls mailbox/ (should stay empty)"
echo "=================================================="
echo ""

incus exec attacker -- python3 /root/poc/drug_spam_attack.py \
    --target "$TARGET" \
    --count "$COUNT" \
    --interval 0.3
