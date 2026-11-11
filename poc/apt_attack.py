#!/usr/bin/env python3
"""
Threat 2 PoC: APT / C2 simulation against zone-aggregator-north honeypot endpoints.
Simulates "low and slow" persistent probing of admin endpoints to trigger Wazuh
frequency rule 100201 (3+ hits in 5 minutes from same IP).

In a real APT demo this would run from a meterpreter session on the compromised
zone-aggregator container (Guide 8 workflow). Here it's a standalone script.

Usage:
    python3 poc/apt_attack.py --target http://<zone-aggregator-north-ip>:5100 --probes 5
"""
import argparse
import time
import urllib.request
import urllib.error
from datetime import datetime

parser = argparse.ArgumentParser(description="APT PoC — honeypot probing")
parser.add_argument("--target", default="http://localhost:5100", help="Zone aggregator URL")
parser.add_argument("--probes", type=int, default=5, help="Number of probe rounds")
parser.add_argument("--delay", type=float, default=30.0, help="Delay between probes (seconds)")
args = parser.parse_args()

HONEYPOT_PATHS = ["/api/admin/config", "/api/admin/metrics"]

print(f"[*] APT PoC: probing {args.target} — {args.probes} rounds, {args.delay}s delay")
print(f"[*] Expected detection: Wazuh rule 100201 after 3+ honeypot hits in 5 minutes")
print(f"[*] Expected response: Wazuh blocks probing IP, zone-north isolated")

for i in range(1, args.probes + 1):
    for path in HONEYPOT_PATHS:
        url = args.target + path
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read(200).decode()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Probe {i} GET {path} -> 200 | {body[:60]}")
        except urllib.error.HTTPError as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Probe {i} GET {path} -> HTTP {e.code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Probe {i} GET {path} -> ERROR {e}")

    if i < args.probes:
        print(f"    ... sleeping {args.delay}s (simulating low-and-slow APT) ...")
        time.sleep(args.delay)

print(f"\n[+] Done. {args.probes} probe rounds x {len(HONEYPOT_PATHS)} endpoints = {args.probes * len(HONEYPOT_PATHS)} requests")
print(f"[+] Check Wazuh: rule 100200 (honeypot hit), 100201 (APT confirmed)")
print(f"[+] Check Prometheus: wazuh_alerts_total{{rule_id='100200'}}")
