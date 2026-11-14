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
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "9200"))

LOG_DIR = "/var/log/threat-blocker"
os.makedirs(LOG_DIR, exist_ok=True)

_logger = logging.getLogger("access")
_logger.setLevel(logging.INFO)
_h = logging.FileHandler(f"{LOG_DIR}/access.log")
_h.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_h)


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
    subprocess.run(
        ["iptables", f"-{flag}", "DOCKER-USER", "-s", ip, "-j", "DROP"],
        check=True,
        capture_output=True,
    )


def _schedule_unblock(ip: str, duration: int):
    import time
    time.sleep(duration)
    try:
        _iptables("D", ip)
        _log("ip_unblocked", ip, f"auto after {duration}s")
    except Exception as e:
        _log("unblock_failed", ip, str(e))


app = FastAPI(title="Threat Blocker", version="1.0.0")


class BlockRequest(BaseModel):
    ip: str
    duration: int = 300


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
    _log("ip_blocked", req.ip, f"duration={req.duration}s")
    threading.Thread(target=_schedule_unblock, args=(req.ip, req.duration), daemon=True).start()
    return {"status": "blocked", "ip": req.ip, "duration": req.duration}


@app.delete("/block/{ip}")
async def unblock(ip: str, x_internal_token: str = Header(None)):
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        _iptables("D", ip)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="iptables failed")
    _log("ip_unblocked", ip, "manual")
    return {"status": "unblocked", "ip": ip}


@app.get("/health")
async def health():
    return {"status": "ok"}
