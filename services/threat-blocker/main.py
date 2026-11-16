"""
Threat Blocker — active-response enforcement point for Wazuh.

Runs with network_mode: host so it shares the Docker host's network namespace
and can write to the DOCKER-USER iptables chain, which affects all container traffic.

Wazuh's block-threat.sh sends a POST /block to this service instead of calling
iptables directly (which would only affect the Wazuh container's own namespace).
"""
import json
import logging
import os
import subprocess
import threading
import time as _time
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import (
    Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
)

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "9200"))

LOG_DIR = "/var/log/threat-blocker"
os.makedirs(LOG_DIR, exist_ok=True)

_logger = logging.getLogger("access")
_logger.setLevel(logging.INFO)
_h = logging.FileHandler(f"{LOG_DIR}/access.log")
_h.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_h)

# ── Prometheus metrics ────────────────────────────────────────────────────────
_prom = CollectorRegistry()

_blocks_total = Counter(
    "threat_blocker_blocks_total",
    "Total IP block events by threat",
    ["ip", "rule_id"],
    registry=_prom,
)
_blocked_since = Gauge(
    "threat_blocker_blocked_since_unix",
    "Unix timestamp when IP was blocked (0 = currently unblocked)",
    ["ip", "rule_id"],
    registry=_prom,
)

# ip -> rule_id so unblock can reset the right gauge label set
_blocked_rule: dict[str, str] = {}
_blocked_lock = threading.Lock()


def _log(event_type: str, ip: str, detail: str = ""):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "ip": ip,
        "detail": detail,
    }
    _logger.info(json.dumps(record))


def _iptables(flag: str, ip: str):
    # DOCKER-USER is the chain Docker reserves for user-defined rules.
    # Rules here are processed before Docker's own FORWARD rules and persist
    # across 'docker restart' (but not across daemon restart — acceptable for demo).
    if flag == "I":
        # Skip insert if an identical rule already exists (prevents duplicate rules
        # when rule 100002 fires multiple times for the same ongoing attack).
        check = subprocess.run(
            ["iptables", "-C", "DOCKER-USER", "-s", ip, "-j", "DROP"],
            capture_output=True,
        )
        if check.returncode == 0:
            return
    elif flag == "D":
        # Remove ALL matching rules, not just the first, to clean up any duplicates
        # that slipped through before this check was added.
        while True:
            result = subprocess.run(
                ["iptables", "-D", "DOCKER-USER", "-s", ip, "-j", "DROP"],
                capture_output=True,
            )
            if result.returncode != 0:
                break
        return
    subprocess.run(
        ["iptables", f"-{flag}", "DOCKER-USER", "-s", ip, "-j", "DROP"],
        check=True,
        capture_output=True,
    )


def _schedule_unblock(ip: str, duration: int, rule_id: str):
    _time.sleep(duration)
    try:
        _iptables("D", ip)
        with _blocked_lock:
            _blocked_rule.pop(ip, None)
        _blocked_since.labels(ip=ip, rule_id=rule_id).set(0)
        _log("ip_unblocked", ip, f"auto after {duration}s")
    except Exception as e:
        _log("unblock_failed", ip, str(e))


app = FastAPI(title="Threat Blocker", version="1.0.0")


class BlockRequest(BaseModel):
    ip: str
    duration: int = 300
    rule_id: str = "unknown"


@app.post("/block")
async def block(req: BlockRequest, x_internal_token: str = Header(None)):
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not req.ip or req.ip in ("-", "unknown"):
        raise HTTPException(status_code=400, detail="no usable IP")
    try:
        _iptables("I", req.ip)
    except subprocess.CalledProcessError as e:
        _log("block_failed", req.ip, e.stderr.decode() if e.stderr else str(e))
        raise HTTPException(status_code=500, detail="iptables failed")
    with _blocked_lock:
        _blocked_rule[req.ip] = req.rule_id
    _blocks_total.labels(ip=req.ip, rule_id=req.rule_id).inc()
    _blocked_since.labels(ip=req.ip, rule_id=req.rule_id).set(_time.time())
    _log("ip_blocked", req.ip, f"rule_id={req.rule_id} duration={req.duration}s")
    threading.Thread(
        target=_schedule_unblock, args=(req.ip, req.duration, req.rule_id), daemon=True
    ).start()
    return {"status": "blocked", "ip": req.ip, "duration": req.duration, "rule_id": req.rule_id}


@app.delete("/block/{ip}")
async def unblock(ip: str, x_internal_token: str = Header(None)):
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        _iptables("D", ip)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="iptables failed")
    with _blocked_lock:
        rule_id = _blocked_rule.pop(ip, "unknown")
    _blocked_since.labels(ip=ip, rule_id=rule_id).set(0)
    _log("ip_unblocked", ip, "manual")
    return {"status": "unblocked", "ip": ip}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(_prom), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"status": "ok"}
