#!/bin/bash
# End-to-end SOA smoke tests.
# Run from the Debian VM after run_all.sh completes.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1)
TOKEN=$(grep "^INTERNAL_TOKEN=" "$PROJECT_DIR/.env" | cut -d= -f2)

PASS=0; FAIL=0

ok()   { echo "[PASS] $1"; ((PASS++)); }
fail() { echo "[FAIL] $1"; ((FAIL++)); }

check_http() {
    local label="$1" url="$2" expected="$3"
    local code
    code=$(curl -sk -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    [ "$code" = "$expected" ] && ok "$label (HTTP $code)" || fail "$label — expected $expected, got $code"
}

check_contains() {
    local label="$1" url="$2" pattern="$3" extra_args="${4:-}"
    local body
    body=$(curl -sk $extra_args "$url" 2>/dev/null || echo "")
    echo "$body" | grep -q "$pattern" && ok "$label" || fail "$label — pattern '$pattern' not found in response"
}

echo "=== Smart City SOA — Smoke Tests ==="
echo "  smartcity-services IP : $SC_IP"
echo ""

# ── 1. External endpoints reachable ─────────────────────────────────────────
echo "--- External endpoints ---"
check_http "Ops Portal up"       "http://$SC_IP:5600"       "200"
check_http "Registry up"         "http://$SC_IP:5050/docs"  "200"
check_http "Prometheus up"       "http://$SC_IP:9090"       "200"
check_http "Grafana up"          "http://$SC_IP:3000"       "200"

# ── 2. Service Registry has registered services ──────────────────────────────
echo ""
echo "--- Service Registry ---"
check_contains "Services registered" \
    "http://$SC_IP:5050/services" \
    "zone" \
    "-H 'x-internal-token: $TOKEN'"

check_contains "Zones listed" \
    "http://$SC_IP:5050/zones" \
    "north"

# ── 3. Internal health checks (via docker exec) ──────────────────────────────
echo ""
echo "--- Internal service health ---"
for svc_port in "ingestion-service:5200" "storage-service:5300" "analytics-service:5400" "alert-service:5500"; do
    svc="${svc_port%%:*}"; port="${svc_port##*:}"
    result=$(incus exec smartcity-services -- bash -c \
        "curl -sk -o /dev/null -w '%{http_code}' http://$svc:$port/health 2>/dev/null || echo 000")
    [ "$result" = "200" ] && ok "$svc /health" || fail "$svc /health — got $result"
done

for zone in north center south; do
    result=$(incus exec smartcity-services -- bash -c \
        "curl -sk -o /dev/null -w '%{http_code}' http://zone-aggregator-$zone:5100/health 2>/dev/null || echo 000")
    [ "$result" = "200" ] && ok "zone-aggregator-$zone /health" || fail "zone-aggregator-$zone /health — got $result"
done

# ── 4. Data flow: wait for zone aggregators to have sent data ────────────────
echo ""
echo "--- Data flow (waiting up to 30s for aggregator cycle) ---"
for i in $(seq 1 6); do
    count=$(incus exec smartcity-services -- bash -c \
        "curl -sk -H 'x-internal-token: $TOKEN' http://storage-service:5300/readings?limit=1 2>/dev/null" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('readings',d if isinstance(d,list) else [])))" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ] 2>/dev/null; then
        ok "Storage has readings (count=$count)"
        break
    fi
    [ "$i" -lt 6 ] && echo "  waiting for data... ($i/6)" && sleep 5 || fail "No readings in storage after 30s"
done

# Analytics summary
result=$(incus exec smartcity-services -- bash -c \
    "curl -sk -H 'x-internal-token: $TOKEN' http://analytics-service:5400/summary 2>/dev/null")
echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)" 2>/dev/null \
    && ok "Analytics /summary returned data" || fail "Analytics /summary failed"

# ── 5. Mail server accepts SMTP ──────────────────────────────────────────────
echo ""
echo "--- Mail server ---"
result=$(incus exec smartcity-services -- bash -c "
python3 -c \"
import smtplib
from email.message import EmailMessage
msg = EmailMessage()
msg['From'] = 'test@smartcity.local'
msg['To'] = 'operator@smartcity.local'
msg['Subject'] = 'SOA Test Email'
msg.set_content('This is a test email from the SOA smoke test.')
s = smtplib.SMTP('mail-server', 25)
s.send_message(msg)
s.quit()
print('OK')
\" 2>&1")
echo "$result" | grep -q "OK" && ok "Mail server accepted SMTP message" || fail "Mail server SMTP failed: $result"

# ── 6. Prometheus scraping services ─────────────────────────────────────────
echo ""
echo "--- Prometheus ---"
check_contains "Prometheus targets up" \
    "http://$SC_IP:9090/api/v1/targets" \
    '"health":"up"'

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
