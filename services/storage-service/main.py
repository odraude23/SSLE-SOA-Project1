import os
import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from contextlib import contextmanager

from fastapi import FastAPI, Request, HTTPException, Query
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

PORT = int(os.getenv("PORT", "5300"))
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
DB_PATH = os.getenv("DB_PATH", "/data/smartcity.db")

LOG_DIR = "/var/log/storage"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
h = logging.FileHandler(f"{LOG_DIR}/access.log")
h.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(h)

app = FastAPI(title="Storage Service", version="1.0.0")
Instrumentator().instrument(app).expose(app)

db_lock = threading.Lock()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sample_count INTEGER,
                interval_seconds INTEGER,
                aqi_avg REAL,
                aqi_min REAL,
                aqi_max REAL,
                temp_avg REAL,
                temp_min REAL,
                temp_max REAL,
                noise_avg REAL,
                noise_min REAL,
                noise_max REAL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zone_ts ON readings(zone, timestamp)")


init_db()


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


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        token = request.headers.get("x-internal-token", "")
        if token != INTERNAL_TOKEN:
            log_access(request, "auth_failed")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


class StorePayload(BaseModel):
    zone: str
    sample_count: int
    interval_seconds: int
    timestamp: str
    aggregated: dict
    raw_samples: list = []


@app.post("/store")
async def store(payload: StorePayload, request: Request):
    agg = payload.aggregated
    aqi = agg.get("aqi", {})
    temp = agg.get("temperature_c", {})
    noise = agg.get("noise_db", {})

    with db_lock:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO readings
                   (zone, timestamp, sample_count, interval_seconds,
                    aqi_avg, aqi_min, aqi_max,
                    temp_avg, temp_min, temp_max,
                    noise_avg, noise_min, noise_max)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload.zone, payload.timestamp, payload.sample_count, payload.interval_seconds,
                    aqi.get("avg"), aqi.get("min"), aqi.get("max"),
                    temp.get("avg"), temp.get("min"), temp.get("max"),
                    noise.get("avg"), noise.get("min"), noise.get("max"),
                ),
            )

    log_access(request, "store_ok", f"zone={payload.zone} ts={payload.timestamp}")
    return {"status": "stored"}


@app.get("/query")
async def query(
    request: Request,
    zone: str = "",
    limit: int = Query(default=100, le=1000),
    since: str = "",
):
    with db_lock:
        with get_db() as conn:
            sql = "SELECT * FROM readings WHERE 1=1"
            params: list = []
            if zone:
                sql += " AND zone = ?"
                params.append(zone)
            if since:
                sql += " AND timestamp >= ?"
                params.append(since)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

    results = [dict(r) for r in rows]
    log_access(request, "query", f"zone={zone} since={since} rows={len(results)}")
    return {"readings": results}


@app.get("/latest")
async def latest(request: Request, zone: str = ""):
    with db_lock:
        with get_db() as conn:
            if zone:
                rows = conn.execute(
                    "SELECT * FROM readings WHERE zone=? ORDER BY timestamp DESC LIMIT 1",
                    (zone,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM readings WHERE (zone, timestamp) IN
                       (SELECT zone, MAX(timestamp) FROM readings GROUP BY zone)"""
                ).fetchall()

    results = [dict(r) for r in rows]
    log_access(request, "latest", f"zone={zone}")
    return {"latest": results}


@app.get("/stats")
async def stats(request: Request, zone: str = ""):
    with db_lock:
        with get_db() as conn:
            if zone:
                row = conn.execute(
                    """SELECT zone,
                              COUNT(*) as records,
                              AVG(aqi_avg) as mean_aqi,
                              AVG(temp_avg) as mean_temp,
                              AVG(noise_avg) as mean_noise,
                              MIN(timestamp) as first_ts,
                              MAX(timestamp) as last_ts
                       FROM readings WHERE zone=? GROUP BY zone""",
                    (zone,)
                ).fetchone()
                rows = [dict(row)] if row else []
            else:
                rows = [
                    dict(r) for r in conn.execute(
                        """SELECT zone,
                                  COUNT(*) as records,
                                  AVG(aqi_avg) as mean_aqi,
                                  AVG(temp_avg) as mean_temp,
                                  AVG(noise_avg) as mean_noise,
                                  MIN(timestamp) as first_ts,
                                  MAX(timestamp) as last_ts
                           FROM readings GROUP BY zone"""
                    ).fetchall()
                ]

    log_access(request, "stats", f"zone={zone}")
    return {"stats": rows}


@app.get("/health")
async def health():
    return {"status": "ok"}
