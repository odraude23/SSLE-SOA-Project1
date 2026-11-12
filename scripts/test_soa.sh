#!/bin/bash
# End-to-end SOA smoke tests.
# Run from the Debian VM after run_all.sh completes.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SC_IP=$(incus list smartcity-services -f csv -c 4 2>/dev/null | grep eth0 | grep -oP '[\d.]+' | head -1)
TOKEN=$(grep "^INTERNAL_TOKEN=" "$PROJECT_DIR/.env" | cut -d= -f2)

PASS=0; FAIL=0
ok()   { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }

check_ext() {
    local label="$1" url="$2" expected="$3"
    local code
    code=$(curl -skL -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    [ "$code" = "$expected" ] && ok "$label (HTTP $code)" || fail "$label — expected $expected, got $code"
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

# ── 2. Prometheus targets ────────────────────────────────────────────────────
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

# ── 3. Internal tests (run inside Docker network) ────────────────────────────
echo ""
echo "--- Pushing internal test runner ---"
incus file push "$PROJECT_DIR/scripts/test_internal.py" \
    smartcity-services/tmp/test_internal.py
incus exec smartcity-services -- bash -c \
    "docker cp /tmp/test_internal.py service-registry:/tmp/test_internal.py"

echo "--- Running internal tests ---"
internal_out=$(incus exec smartcity-services -- bash -c \
    "docker exec service-registry python3 /tmp/test_internal.py '$TOKEN'" 2>&1 || true)
echo "$internal_out"

int_pass=$(echo "$internal_out" | grep -c "^\[PASS\]" || true)
int_fail=$(echo "$internal_out" | grep -c "^\[FAIL\]" || true)
PASS=$((PASS + int_pass))
FAIL=$((FAIL + int_fail))

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
