import os
import json
import math
import time
import uuid
import random
import threading
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge

ZONE = os.getenv("ZONE", "north")
PORT = int(os.getenv("PORT", "5100"))
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://service-registry:5050")
INGESTION_URL = os.getenv("INGESTION_URL", "http://ingestion-service:5200")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
AGGREGATION_INTERVAL = int(os.getenv("AGGREGATION_INTERVAL", "10"))
NUM_SENSORS = int(os.getenv("NUM_SENSORS", "3"))

ZONE_COORDS = {
    "north":  {"lat": 40.65, "lon": -8.63, "description": "Northern district"},
    "center": {"lat": 40.63, "lon": -8.65, "description": "Central district"},
    "south":  {"lat": 40.61, "lon": -8.67, "description": "Southern district"},
}

LOG_DIR = f"/var/log/zone-aggregator-{ZONE}"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
handler = logging.FileHandler(f"{LOG_DIR}/access.log")
handler.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(handler)

app = FastAPI(title=f"Zone Aggregator ({ZONE})", version="1.0.0")
Instrumentator().instrument(app).expose(app)

zone_aqi_gauge = Gauge("smartcity_zone_aqi_avg", "Zone average AQI index", ["zone"])
zone_temp_gauge = Gauge("smartcity_zone_temp_avg", "Zone average temperature Celsius", ["zone"])
zone_noise_gauge = Gauge("smartcity_zone_noise_avg", "Zone average noise dB", ["zone"])

sensor_buffer: list[dict] = []
buffer_lock = threading.Lock()

INSTANCE_ID: Optional[str] = None
SENSOR_IDS: list[str] = []


def log_access(req: Request, action: str, detail: str = ""):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": req.client.host if req.client else "unknown",
        "method": req.method,
        "path": str(req.url.path),
        "event_type": action,
        "detail": detail,
    }
    access_logger.info(json.dumps(record))


def log_event(action: str, detail: str = ""):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": action,
        "detail": detail,
        "zone": ZONE,
    }
    access_logger.info(json.dumps(record))


def headers():
    return {"x-internal-token": INTERNAL_TOKEN}


def register_with_registry():
    global INSTANCE_ID, SENSOR_IDS
    coords = ZONE_COORDS.get(ZONE, {"lat": 0, "lon": 0, "description": ZONE})
    payload = {
        "name": f"zone-aggregator-{ZONE}",
        "zone": ZONE,
        "url": f"http://zone-aggregator-{ZONE}:{PORT}",
        "location": coords,
        "metadata": {"sensors_managed": NUM_SENSORS, "aggregation_interval": AGGREGATION_INTERVAL},
    }
    for attempt in range(10):
        try:
            resp = requests.post(f"{REGISTRY_URL}/register", json=payload, headers=headers(), timeout=5)
            if resp.status_code == 200:
                INSTANCE_ID = resp.json()["instance_id"]
                log_event("registered", f"instance_id={INSTANCE_ID}")
                break
        except Exception:
            pass
        time.sleep(3 + attempt)

    for i in range(1, NUM_SENSORS + 1):
        sensor_payload = {
            "name": f"sensor-{ZONE}-{i}",
            "zone": ZONE,
            "url": f"http://zone-aggregator-{ZONE}:{PORT}/sensors/{i}",
            "location": coords,
            "metadata": {"type": "sensor", "parent": f"zone-aggregator-{ZONE}"},
        }
        try:
            resp = requests.post(f"{REGISTRY_URL}/register", json=sensor_payload, headers=headers(), timeout=5)
            if resp.status_code == 200:
                SENSOR_IDS.append(resp.json()["instance_id"])
        except Exception:
            pass


def heartbeat_loop():
    while True:
        time.sleep(30)
        ids = [INSTANCE_ID] + SENSOR_IDS if INSTANCE_ID else []
        for iid in ids:
            if not iid:
                continue
            try:
                requests.post(
                    f"{REGISTRY_URL}/heartbeat",
                    json={"instance_id": iid},
                    headers=headers(),
                    timeout=3,
                )
            except Exception:
                pass


def _simulate_reading(sensor_id: int, ts: float) -> dict:
    t = ts
    aqi = max(0, min(500, 60 + 30 * math.sin(t / 3600) + random.gauss(0, 5)))
    temp = 18 + 8 * math.sin(t / 86400 * 2 * math.pi) + random.gauss(0, 1)
    noise = max(30, min(120, 55 + 15 * math.sin(t / 7200) + random.gauss(0, 3)))
    return {
        "sensor_id": sensor_id,
        "aqi": round(aqi, 1),
        "temperature_c": round(temp, 2),
        "noise_db": round(noise, 1),
        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
    }


def sensor_thread(sensor_id: int):
    while True:
        reading = _simulate_reading(sensor_id, time.time())
        with buffer_lock:
            sensor_buffer.append(reading)
        time.sleep(2)


def aggregation_loop():
    while True:
        time.sleep(AGGREGATION_INTERVAL)
        with buffer_lock:
            if not sensor_buffer:
                continue
            batch = list(sensor_buffer)
            sensor_buffer.clear()

        def agg(key):
            vals = [r[key] for r in batch]
            return {"avg": round(sum(vals) / len(vals), 2), "min": round(min(vals), 2), "max": round(max(vals), 2)}

        payload = {
            "zone": ZONE,
            "sample_count": len(batch),
            "interval_seconds": AGGREGATION_INTERVAL,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "aggregated": {
                "aqi": agg("aqi"),
                "temperature_c": agg("temperature_c"),
                "noise_db": agg("noise_db"),
            },
            "raw_samples": batch,
        }
        zone_aqi_gauge.labels(zone=ZONE).set(payload["aggregated"]["aqi"]["avg"])
        zone_temp_gauge.labels(zone=ZONE).set(payload["aggregated"]["temperature_c"]["avg"])
        zone_noise_gauge.labels(zone=ZONE).set(payload["aggregated"]["noise_db"]["avg"])

        try:
            resp = requests.post(
                f"{INGESTION_URL}/ingest",
                json=payload,
                headers=headers(),
                timeout=10,
            )
            log_event("batch_sent", f"samples={len(batch)} status={resp.status_code}")
        except Exception as e:
            log_event("batch_failed", str(e))


@app.on_event("startup")
async def startup():
    threading.Thread(target=register_with_registry, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    for i in range(1, NUM_SENSORS + 1):
        threading.Thread(target=sensor_thread, args=(i,), daemon=True).start()
    threading.Thread(target=aggregation_loop, daemon=True).start()


# --- Honeypot endpoints for APT detection ---

@app.get("/api/admin/config")
async def honeypot_config(request: Request):
    log_event("HONEYPOT_HIT", f"path=/api/admin/config ip={request.client.host if request.client else 'unknown'}")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": request.client.host if request.client else "unknown",
        "method": request.method,
        "path": "/api/admin/config",
        "event_type": "HONEYPOT_HIT",
        "rule_id": "100200",
        "zone": ZONE,
    }
    access_logger.info(json.dumps(record))
    # Simulates a misconfigured admin endpoint that leaks the internal service token.
    # In a real deployment this mirrors Spring Boot /actuator/env or a debug endpoint
    # left enabled — attacker reads the token and uses it to impersonate internal services.
    return {"config": {"debug": False, "version": "1.0.0", "zone": ZONE, "internal_token": INTERNAL_TOKEN}}


@app.get("/api/admin/metrics")
async def honeypot_metrics(request: Request):
    log_event("HONEYPOT_HIT", f"path=/api/admin/metrics ip={request.client.host if request.client else 'unknown'}")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": request.client.host if request.client else "unknown",
        "method": request.method,
        "path": "/api/admin/metrics",
        "event_type": "HONEYPOT_HIT",
        "rule_id": "100200",
        "zone": ZONE,
    }
    access_logger.info(json.dumps(record))
    return {"internal_metrics": {"uptime": time.time(), "zone": ZONE}}


@app.get("/sensors/{sensor_id}")
async def sensor_info(sensor_id: int, request: Request):
    log_access(request, "sensor_info", f"sensor_id={sensor_id}")
    reading = _simulate_reading(sensor_id, time.time())
    return {"zone": ZONE, "sensor": sensor_id, "latest": reading}


@app.get("/status")
async def status(request: Request):
    log_access(request, "status")
    with buffer_lock:
        buffered = len(sensor_buffer)
    return {
        "zone": ZONE,
        "instance_id": INSTANCE_ID,
        "sensor_ids": SENSOR_IDS,
        "buffered_readings": buffered,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "zone": ZONE}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    log_access(request, "not_found", "path not registered")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
