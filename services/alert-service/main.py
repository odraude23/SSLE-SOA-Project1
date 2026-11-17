import os
import json
import smtplib
import logging
import threading
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "5500"))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "alerts@smartcity.local")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "operator@smartcity.local")

AQI_THRESHOLD = float(os.getenv("AQI_THRESHOLD", "150"))
TEMP_THRESHOLD = float(os.getenv("TEMP_THRESHOLD", "35"))
NOISE_THRESHOLD = float(os.getenv("NOISE_THRESHOLD", "80"))

LOG_DIR = "/var/log/alert-service"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
h = logging.FileHandler(f"{LOG_DIR}/access.log")
h.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(h)

mail_logger = logging.getLogger("mail")
mail_logger.setLevel(logging.INFO)
mh = logging.FileHandler(f"{LOG_DIR}/mail.log")
mh.setFormatter(logging.Formatter("%(message)s"))
mail_logger.addHandler(mh)

app = FastAPI(title="Alert Service", version="1.0.0")
Instrumentator().instrument(app).expose(app)

CIRCUIT_THRESHOLD = int(os.getenv("CIRCUIT_THRESHOLD", "10"))  # emails in 60s
CIRCUIT_COOLDOWN  = int(os.getenv("CIRCUIT_COOLDOWN",  "300")) # seconds to stay open

emails_sent = Counter("alert_emails_total", "Total alert emails sent", ["zone", "metric"])
emails_rate = Counter("alert_email_rate_per_min", "Alert emails in current minute")

rate_lock = threading.Lock()
rate_window: list[float] = []
circuit_open_until: float = 0.0


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


def log_mail(action: str, zone: str, subject: str, detail: str = ""):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": action,
        "zone": zone,
        "subject": subject,
        "detail": detail,
    }
    mail_logger.info(json.dumps(record))
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


def send_email(zone: str, metric: str, value: float, threshold: float):
    global circuit_open_until
    now = time.time()

    with rate_lock:
        # Drop stale entries outside the 60s window
        rate_window[:] = [t for t in rate_window if now - t <= 60]

        if now < circuit_open_until:
            log_mail("circuit_breaker_blocked", zone,
                     f"[CIRCUIT OPEN] email suppressed",
                     f"resets_in={int(circuit_open_until - now)}s")
            return

        if len(rate_window) >= CIRCUIT_THRESHOLD:
            circuit_open_until = now + CIRCUIT_COOLDOWN
            log_mail("circuit_breaker_open", zone,
                     f"[CIRCUIT OPEN] email flood detected",
                     f"rate={len(rate_window)}/60s threshold={CIRCUIT_THRESHOLD} cooldown={CIRCUIT_COOLDOWN}s")
            return

    subject = f"[ALERT][{zone.upper()}] {metric.upper()} exceeded threshold: {value} > {threshold}"
    body = (
        f"Smart City Environmental Monitor\n\n"
        f"Zone: {zone}\n"
        f"Metric: {metric}\n"
        f"Current value: {value}\n"
        f"Threshold: {threshold}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}\n"
    )
    msg = MIMEMultipart()
    msg["From"] = ALERT_EMAIL_FROM
    msg["To"] = ALERT_EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as server:
            server.sendmail(ALERT_EMAIL_FROM, [ALERT_EMAIL_TO], msg.as_string())
        emails_sent.labels(zone=zone, metric=metric).inc()
        emails_rate.inc()
        with rate_lock:
            rate_window.append(time.time())
        log_mail("email_sent", zone, subject)
    except Exception as e:
        log_mail("email_failed", zone, subject, str(e))


class CheckRequest(BaseModel):
    zone: str
    aggregated: dict
    timestamp: str = ""


@app.post("/check")
async def check(payload: CheckRequest, request: Request):
    agg = payload.aggregated
    alerts = []

    aqi_avg = agg.get("aqi", {}).get("avg")
    if aqi_avg is not None and aqi_avg > AQI_THRESHOLD:
        threading.Thread(target=send_email, args=(payload.zone, "AQI", aqi_avg, AQI_THRESHOLD), daemon=True).start()
        alerts.append({"metric": "aqi", "value": aqi_avg, "threshold": AQI_THRESHOLD})

    temp_avg = agg.get("temperature_c", {}).get("avg")
    if temp_avg is not None and temp_avg > TEMP_THRESHOLD:
        threading.Thread(target=send_email, args=(payload.zone, "temperature_c", temp_avg, TEMP_THRESHOLD), daemon=True).start()
        alerts.append({"metric": "temperature_c", "value": temp_avg, "threshold": TEMP_THRESHOLD})

    noise_avg = agg.get("noise_db", {}).get("avg")
    if noise_avg is not None and noise_avg > NOISE_THRESHOLD:
        threading.Thread(target=send_email, args=(payload.zone, "noise_db", noise_avg, NOISE_THRESHOLD), daemon=True).start()
        alerts.append({"metric": "noise_db", "value": noise_avg, "threshold": NOISE_THRESHOLD})

    log_access(request, "check", f"zone={payload.zone} alerts={len(alerts)}")
    return {"zone": payload.zone, "alerts_triggered": len(alerts), "alerts": alerts}


@app.get("/email-rate")
async def email_rate(request: Request):
    now = time.time()
    with rate_lock:
        recent = [t for t in rate_window if now - t <= 60]
    log_access(request, "email_rate")
    return {"emails_last_60s": len(recent)}


@app.get("/health")
async def health():
    return {"status": "ok"}
