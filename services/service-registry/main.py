import os
import json
import uuid
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

LOG_DIR = "/var/log/registry"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
handler = logging.FileHandler(f"{LOG_DIR}/access.log")
handler.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(handler)

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "60"))

app = FastAPI(title="Service Registry", version="1.0.0")
Instrumentator().instrument(app).expose(app)

services: dict[str, dict] = {}
lock = threading.Lock()


class Location(BaseModel):
    lat: float
    lon: float
    description: str = ""


class RegisterRequest(BaseModel):
    name: str
    zone: str
    url: str
    location: Optional[Location] = None
    metadata: dict = {}


class HeartbeatRequest(BaseModel):
    instance_id: str


def log_access(req: Request, action: str, detail: str = ""):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": req.client.host if req.client else "unknown",
        "method": req.method,
        "path": str(req.url.path),
        "action": action,
        "detail": detail,
    }
    access_logger.info(json.dumps(record))


def prune_stale():
    while True:
        time.sleep(30)
        cutoff = time.time() - HEARTBEAT_TIMEOUT
        with lock:
            stale = [iid for iid, s in services.items() if s["last_heartbeat"] < cutoff]
            for iid in stale:
                services.pop(iid)
                access_logger.info(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "pruned",
                    "instance_id": iid,
                }))


threading.Thread(target=prune_stale, daemon=True).start()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        token = request.headers.get("x-internal-token", "")
        if token != INTERNAL_TOKEN:
            log_access(request, "auth_failed")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.post("/register")
async def register(body: RegisterRequest, request: Request):
    instance_id = str(uuid.uuid4())
    entry = {
        "instance_id": instance_id,
        "name": body.name,
        "zone": body.zone,
        "url": body.url,
        "location": body.location.model_dump() if body.location else None,
        "metadata": body.metadata,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "last_heartbeat": time.time(),
    }
    with lock:
        services[instance_id] = entry
    log_access(request, "register", f"name={body.name} zone={body.zone} id={instance_id}")
    return {"instance_id": instance_id}


@app.post("/heartbeat")
async def heartbeat(body: HeartbeatRequest, request: Request):
    with lock:
        if body.instance_id not in services:
            raise HTTPException(status_code=404, detail="Instance not found")
        services[body.instance_id]["last_heartbeat"] = time.time()
    log_access(request, "heartbeat", f"id={body.instance_id}")
    return {"status": "ok"}


@app.get("/lookup")
async def lookup(request: Request, name: str = "", zone: str = ""):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    with lock:
        results = [
            s for s in services.values()
            if s["last_heartbeat"] >= cutoff
            and (not name or s["name"] == name)
            and (not zone or s["zone"] == zone)
        ]
    log_access(request, "lookup", f"name={name} zone={zone} hits={len(results)}")
    return {"services": results}


@app.get("/zones")
async def get_zones(request: Request):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    with lock:
        zones = {}
        for s in services.values():
            if s["last_heartbeat"] < cutoff:
                continue
            z = s["zone"]
            if z not in zones:
                zones[z] = {"zone": z, "services": [], "location": s.get("location")}
            zones[z]["services"].append(s["name"])
    log_access(request, "get_zones")
    return {"zones": list(zones.values())}


@app.get("/zones/{zone}/services")
async def get_zone_services(zone: str, request: Request):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    with lock:
        results = [
            s for s in services.values()
            if s["zone"] == zone and s["last_heartbeat"] >= cutoff
        ]
    log_access(request, "get_zone_services", f"zone={zone}")
    return {"zone": zone, "services": results}


@app.get("/zones/{zone}/status")
async def get_zone_status(zone: str, request: Request):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    with lock:
        zone_services = [s for s in services.values() if s["zone"] == zone]
        active = [s for s in zone_services if s["last_heartbeat"] >= cutoff]

    status = "healthy" if zone_services and len(active) == len(zone_services) else \
             "degraded" if active else \
             "unknown"
    log_access(request, "get_zone_status", f"zone={zone} status={status}")
    return {
        "zone": zone,
        "status": status,
        "total": len(zone_services),
        "active": len(active),
    }


@app.get("/services")
async def list_services(request: Request):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    with lock:
        active = [s for s in services.values() if s["last_heartbeat"] >= cutoff]
    log_access(request, "list_services", f"count={len(active)}")
    return {"services": active}


@app.get("/health")
async def health():
    return {"status": "ok"}
