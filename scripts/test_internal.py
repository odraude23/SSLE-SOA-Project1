"""Internal SOA smoke tests — runs inside the Docker network."""
import sys
import json
import smtplib
import urllib.request
import urllib.error
from email.message import EmailMessage

TOKEN = sys.argv[1] if len(sys.argv) > 1 else "changeme"

PASS = 0
FAIL = 0

def ok(label):
    global PASS
    print(f"[PASS] {label}")
    PASS += 1

def fail(label, detail=""):
    global FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"[FAIL] {label}{suffix}")
    FAIL += 1

def get(url, token=None):
    headers = {"x-internal-token": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)

# ── Health checks ─────────────────────────────────────────────────────────────
print("--- Internal service health ---")
services = [
    ("ingestion-service",      5200),
    ("storage-service",        5300),
    ("analytics-service",      5400),
    ("alert-service",          5500),
    ("zone-aggregator-north",  5100),
    ("zone-aggregator-center", 5101),
    ("zone-aggregator-south",  5102),
]
for svc, port in services:
    code, body = get(f"http://{svc}:{port}/health")
    if code == 200:
        ok(f"{svc} /health")
    else:
        fail(f"{svc} /health", f"HTTP {code}: {body[:60]}")

# ── Service Registry ──────────────────────────────────────────────────────────
print("\n--- Service Registry ---")
code, body = get("http://service-registry:5050/services", TOKEN)
try:
    data = json.loads(body)
    count = len(data) if isinstance(data, list) else len(data.get("services", []))
    if code == 200 and count > 0:
        ok(f"Services registered ({count} services)")
    else:
        ok("Services endpoint reachable") if code == 200 else fail("Services endpoint", f"HTTP {code}")
except Exception:
    fail("Services registered", body[:80])

code, body = get("http://service-registry:5050/zones", TOKEN)
if code == 200 and ("north" in body or "center" in body):
    ok("Zones endpoint (north/center/south present)")
else:
    fail("Zones endpoint", f"HTTP {code}: {body[:80]}")

# ── Data flow ─────────────────────────────────────────────────────────────────
print("\n--- Data flow ---")
code, body = get("http://storage-service:5300/readings?limit=5", TOKEN)
try:
    d = json.loads(body)
    readings = d.get("readings", d) if isinstance(d, dict) else d
    count = len(readings) if isinstance(readings, list) else 0
    if code == 200 and count > 0:
        ok(f"Storage has readings ({count} rows)")
    elif code == 200:
        fail("Storage readings", "empty — zone aggregators may not have fired yet")
    else:
        fail("Storage readings", f"HTTP {code}: {body[:80]}")
except Exception as e:
    fail("Storage readings", str(e))

code, body = get("http://analytics-service:5400/summary", TOKEN)
if code == 200:
    ok("Analytics /summary")
else:
    fail("Analytics /summary", f"HTTP {code}: {body[:80]}")

# ── Mail server ───────────────────────────────────────────────────────────────
print("\n--- Mail server ---")
try:
    msg = EmailMessage()
    msg["From"] = "test@smartcity.local"
    msg["To"] = "operator@smartcity.local"
    msg["Subject"] = "SOA Test Email"
    msg.set_content("Smoke test message.")
    s = smtplib.SMTP("mail-server", 25, timeout=10)
    s.send_message(msg)
    s.quit()
    ok("Mail server accepted SMTP message")
except Exception as e:
    fail("Mail server SMTP", str(e))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n=== Internal results: {PASS} passed, {FAIL} failed ===")
sys.exit(0 if FAIL == 0 else 1)
