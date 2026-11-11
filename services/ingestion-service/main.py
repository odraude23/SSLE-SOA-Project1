import os
import json
import logging
import threading
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://service-registry:5050")
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:5300")
ALERT_URL = os.getenv("ALERT_URL", "http://alert-service:5500")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "5200"))

LOG_DIR = "/var/log/ingestion"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
h = logging.FileHandler(f"{LOG_DIR}/access.log")
h.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(h)

app = FastAPI(title="Ingestion Service", version="1.0.0")
Instrumentator().instrument(app).expose(app)

VALID_AQI = (0, 500)
VALID_TEMP = (-30, 60)
VALID_NOISE = (0, 150)


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


class AggregatedMetric(BaseModel):
    avg: float
    min: float
    max: float


class AggregatedPayload(BaseModel):
    zone: str
    sample_count: int
    interval_seconds: int
    timestamp: str
    aggregated: dict
    raw_samples: list = []


def validate_aggregated(agg: dict) -> list[str]:
    errors = []
    aqi = agg.get("aqi", {})
    temp = agg.get("temperature_c", {})
    noise = agg.get("noise_db", {})

    for label, metric, (lo, hi) in [
        ("aqi", aqi, VALID_AQI),
        ("temperature_c", temp, VALID_TEMP),
        ("noise_db", noise, VALID_NOISE),
    ]:
        avg = metric.get("avg")
        if avg is not None and not (lo <= avg <= hi):
            errors.append(f"{label}.avg={avg} out of range [{lo},{hi}]")
    return errors


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        token = request.headers.get("x-internal-token", "")
        if token != INTERNAL_TOKEN:
            log_access(request, "auth_failed")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.post("/ingest")
async def ingest(payload: AggregatedPayload, request: Request):
    errors = validate_aggregated(payload.aggregated)
    if errors:
        detail = "; ".join(errors)
        log_access(request, "validation_failed", detail)
        raise HTTPException(status_code=422, detail=f"Validation failed: {detail}")

    try:
        resp = requests.post(
            f"{STORAGE_URL}/store",
            json=payload.model_dump(),
            headers=headers(),
            timeout=10,
        )
        log_access(request, "ingest_ok", f"zone={payload.zone} samples={payload.sample_count} storage={resp.status_code}")

        def _notify_alert():
            try:
                requests.post(
                    f"{ALERT_URL}/check",
                    json={"zone": payload.zone, "aggregated": payload.aggregated, "timestamp": payload.timestamp},
                    headers=headers(),
                    timeout=5,
                )
            except Exception:
                pass
        threading.Thread(target=_notify_alert, daemon=True).start()

        return {"status": "stored", "zone": payload.zone, "sample_count": payload.sample_count}
    except Exception as e:
        log_access(request, "ingest_storage_error", str(e))
        raise HTTPException(status_code=503, detail="Storage unavailable")


@app.get("/health")
async def health():
    return {"status": "ok"}
