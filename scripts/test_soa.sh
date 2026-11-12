#!/bin/bash
# End-to-end SOA smoke tests.
# Run from the Debian VM after run_all.sh completes.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1)
TOKEN=$(grep "^INTERNAL_TOKEN=" "$PROJECT_DIR/.env" | cut -d= -f2)

PASS=0; FAIL=0
ok()   { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }

# Check HTTP status from the Debian VM (follows redirects)
check_ext() {
    local label="$1" url="$2" expected="$3"
    local code
    code=$(curl -skL -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    [ "$code" = "$expected" ] && ok "$label (HTTP $code)" || fail "$label — expected $expected, got $code"
}

# Run python3 inside the Docker network via docker compose exec
dexec() {
    incus exec smartcity-services -- bash -c \
        "cd /home/ubuntu/smartcity && docker compose exec -T service-registry python3 -c '$1' 2>/dev/null"
}

check_health() {
    local svc="$1" port="$2"
    local code
    code=$(dexec "
import urllib.request
try:
    r = urllib.request.urlopen('http://$svc:$port/health', timeout=5)
    print(r.status)
except Exception as e:
    print('ERR', e)
" || echo "ERR")
    echo "$code" | grep -q "^200" && ok "$svc /health" || fail "$svc /health — got $code"
}

check_int() {
    local label="$1" url="$2" pattern="$3"
    local body
    body=$(dexec "
import urllib.request, json
req = urllib.request.Request('$url', headers={'x-internal-token':'$TOKEN'})
try:
    r = urllib.request.urlopen(req, timeout=5)
    print(r.read().decode())
except Exception as e:
    print('ERR', e)
" || echo "ERR")
    echo "$body" | grep -q "$pattern" \
        && ok "$label" \
        || fail "$label — '$pattern' not found (got: ${body:0:100})"
}

echo "=== Smart City SOA — Smoke Tests ==="
echo "  smartcity-services IP : $SC_IP"
echo ""

# ── 1. External endpoints ────────────────────────────────────────────────────
echo "--- External endpoints ---"
check_ext "Ops Portal"  "http://$SC_IP:5600"       "200"
check_ext "Registry"    "http://$SC_IP:5050/docs"  "200"
check_ext "Prometheus"  "http://$SC_IP:9090"       "200"
check_ext "Grafana"     "http://$SC_IP:3000"       "200"

# ── 2. Service Registry ──────────────────────────────────────────────────────
echo ""
echo "--- Service Registry ---"
check_int "Services registered" "http://service-registry:5050/services" "name"
check_int "Zones endpoint"      "http://service-registry:5050/zones"    "north"

# ── 3. Internal health checks ────────────────────────────────────────────────
echo ""
echo "--- Internal service health ---"
check_health "ingestion-service"      5200
check_health "storage-service"        5300
check_health "analytics-service"      5400
check_health "alert-service"          5500
check_health "zone-aggregator-north"  5100
check_health "zone-aggregator-center" 5101
check_health "zone-aggregator-south"  5102

# ── 4. Data flow ─────────────────────────────────────────────────────────────
echo ""
echo "--- Data flow (waiting up to 30s for aggregator cycle) ---"
for i in $(seq 1 6); do
    body=$(dexec "
import urllib.request, json
req = urllib.request.Request('http://storage-service:5300/readings?limit=5', headers={'x-internal-token':'$TOKEN'})
try:
    r = urllib.request.urlopen(req, timeout=5)
    print(r.read().decode())
except: print('[]')
" || echo "[]")
    count=$(echo "$body" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    r=d.get('readings',d) if isinstance(d,dict) else d
    print(len(r) if isinstance(r,list) else 0)
except: print(0)" 2>/dev/null || echo 0)
    if [ "$count" -gt "0" ] 2>/dev/null; then
        ok "Storage has readings (count=$count)"
        break
    fi
    [ "$i" -lt 6 ] && echo "  waiting... ($i/6)" && sleep 5 \
        || fail "No readings in storage after 30s"
done

check_int "Analytics /summary" "http://analytics-service:5400/summary" "."

# ── 5. Mail server ───────────────────────────────────────────────────────────
echo ""
echo "--- Mail server ---"
result=$(dexec "
import smtplib
from email.message import EmailMessage
msg = EmailMessage()
msg['From'] = 'test@smartcity.local'
msg['To'] = 'operator@smartcity.local'
msg['Subject'] = 'SOA Test Email'
msg.set_content('Smoke test message.')
try:
    s = smtplib.SMTP('mail-server', 25, timeout=10)
    s.send_message(msg)
    s.quit()
    print('OK')
except Exception as e:
    print('ERR', e)
" || echo "ERR")
echo "$result" | grep -q "OK" \
    && ok "Mail server accepted SMTP message" \
    || fail "Mail server SMTP — $result"

# ── 6. Prometheus targets ────────────────────────────────────────────────────
echo ""
echo "--- Prometheus ---"
body=$(curl -sk "http://$SC_IP:9090/api/v1/targets" 2>/dev/null || echo "{}")
up_count=$(echo "$body" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(sum(1 for t in d.get('data',{}).get('activeTargets',[]) if t.get('health')=='up'))
except: print(0)" 2>/dev/null || echo 0)
[ "$up_count" -gt "0" ] \
    && ok "Prometheus has $up_count targets up" \
    || fail "Prometheus — no targets up"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
