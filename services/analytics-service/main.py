import os
import json
import logging
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request, Query
from prometheus_fastapi_instrumentator import Instrumentator

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:5300")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "5400"))

LOG_DIR = "/var/log/analytics"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
h = logging.FileHandler(f"{LOG_DIR}/access.log")
h.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(h)

app = FastAPI(title="Analytics Service", version="1.0.0")
Instrumentator().instrument(app).expose(app)


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


def headers():
    return {"x-internal-token": INTERNAL_TOKEN}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        token = request.headers.get("x-internal-token", "")
        if token != INTERNAL_TOKEN:
            log_access(request, "auth_failed")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/summary")
async def summary(request: Request):
    try:
        resp = requests.get(f"{STORAGE_URL}/stats", headers=headers(), timeout=10)
        data = resp.json()
    except Exception as e:
        log_access(request, "summary_error", str(e))
        return {"error": "storage unavailable"}

    log_access(request, "summary")
    return data


@app.get("/zone/{zone}")
async def zone_analytics(zone: str, request: Request, limit: int = Query(default=50, le=500)):
    try:
        resp = requests.get(
            f"{STORAGE_URL}/query",
            params={"zone": zone, "limit": limit},
            headers=headers(),
            timeout=10,
        )
        readings = resp.json().get("readings", [])
    except Exception as e:
        log_access(request, "zone_error", str(e))
        return {"zone": zone, "error": "storage unavailable"}

    if not readings:
        log_access(request, "zone_empty", f"zone={zone}")
        return {"zone": zone, "readings": []}

    aqi_vals = [r["aqi_avg"] for r in readings if r.get("aqi_avg") is not None]
    temp_vals = [r["temp_avg"] for r in readings if r.get("temp_avg") is not None]
    noise_vals = [r["noise_avg"] for r in readings if r.get("noise_avg") is not None]

    def safe_stats(vals):
        if not vals:
            return {}
        return {"avg": round(sum(vals) / len(vals), 2), "min": round(min(vals), 2), "max": round(max(vals), 2)}

    log_access(request, "zone_analytics", f"zone={zone} records={len(readings)}")
    return {
        "zone": zone,
        "record_count": len(readings),
        "aqi": safe_stats(aqi_vals),
        "temperature_c": safe_stats(temp_vals),
        "noise_db": safe_stats(noise_vals),
        "latest_readings": readings[:10],
    }


@app.get("/latest")
async def latest(request: Request):
    try:
        resp = requests.get(f"{STORAGE_URL}/latest", headers=headers(), timeout=10)
        data = resp.json()
    except Exception as e:
        log_access(request, "latest_error", str(e))
        return {"error": "storage unavailable"}
    log_access(request, "latest")
    return data


@app.get("/health")
async def health():
    return {"status": "ok"}
