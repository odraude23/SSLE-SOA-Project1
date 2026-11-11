import os
import json
import logging
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from prometheus_fastapi_instrumentator import Instrumentator

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://service-registry:5050")
ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://analytics-service:5400")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "5600"))

LOG_DIR = "/var/log/ops-portal"
os.makedirs(LOG_DIR, exist_ok=True)

access_logger = logging.getLogger("access")
access_logger.setLevel(logging.INFO)
h = logging.FileHandler(f"{LOG_DIR}/access.log")
h.setFormatter(logging.Formatter("%(message)s"))
access_logger.addHandler(h)

app = FastAPI(title="Ops Portal", version="1.0.0")
Instrumentator().instrument(app).expose(app)

ZONES = ["north", "center", "south"]


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


def iheaders():
    return {"x-internal-token": INTERNAL_TOKEN}


def fetch_zone_data():
    zone_data = {}
    for zone in ZONES:
        try:
            resp = requests.get(
                f"{ANALYTICS_URL}/zone/{zone}",
                headers=iheaders(),
                timeout=5,
            )
            zone_data[zone] = resp.json()
        except Exception:
            zone_data[zone] = {"zone": zone, "error": "unavailable"}
    return zone_data


def fetch_zone_statuses():
    statuses = {}
    for zone in ZONES:
        try:
            resp = requests.get(
                f"{REGISTRY_URL}/zones/{zone}/status",
                headers=iheaders(),
                timeout=3,
            )
            statuses[zone] = resp.json()
        except Exception:
            statuses[zone] = {"zone": zone, "status": "unknown"}
    return statuses


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart City Ops Portal</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }
  header { background: #1e293b; padding: 1rem 2rem; border-bottom: 1px solid #334155;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.3rem; font-weight: 600; color: #38bdf8; }
  header span { font-size: 0.8rem; color: #64748b; }
  main { padding: 2rem; max-width: 1200px; margin: 0 auto; }
  .zone-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-top: 1.5rem; }
  .zone-card { background: #1e293b; border-radius: 12px; padding: 1.5rem; border: 1px solid #334155; }
  .zone-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
  .zone-name { font-size: 1.1rem; font-weight: 600; text-transform: capitalize; }
  .badge { padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }
  .badge-healthy { background: #14532d; color: #4ade80; }
  .badge-degraded { background: #7c2d12; color: #fb923c; }
  .badge-unknown { background: #1e293b; color: #94a3b8; border: 1px solid #475569; }
  .metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.8rem; }
  .metric { background: #0f172a; border-radius: 8px; padding: 0.8rem; text-align: center; }
  .metric-label { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
  .metric-value { font-size: 1.4rem; font-weight: 700; margin: 0.2rem 0; }
  .metric-unit { font-size: 0.75rem; color: #64748b; }
  .aqi-good { color: #4ade80; }
  .aqi-moderate { color: #facc15; }
  .aqi-unhealthy { color: #f97316; }
  .aqi-hazardous { color: #ef4444; }
  .error-card { color: #f87171; font-size: 0.85rem; }
  .refresh-bar { text-align: right; margin-bottom: 1rem; font-size: 0.8rem; color: #475569; }
  #last-update { color: #94a3b8; }
</style>
</head>
<body>
<header>
  <h1>&#127961; Smart City Environmental Monitor</h1>
  <span id="last-update">Loading...</span>
</header>
<main>
  <div class="refresh-bar">Auto-refresh every 10s &nbsp;|&nbsp; <a href="/api/data" style="color:#38bdf8">Raw JSON</a></div>
  <div class="zone-grid" id="zone-grid">Loading zones...</div>
</main>
<script>
function aqiClass(v) {
  if (v === undefined || v === null) return '';
  if (v <= 50) return 'aqi-good';
  if (v <= 100) return 'aqi-moderate';
  if (v <= 200) return 'aqi-unhealthy';
  return 'aqi-hazardous';
}

function metricValue(v) {
  return v !== undefined && v !== null ? v : '—';
}

function renderZone(zone, data, status) {
  const agg = data.aqi || {};
  const temp = data.temperature_c || {};
  const noise = data.noise_db || {};
  const statusCls = status.status === 'healthy' ? 'badge-healthy' :
                    status.status === 'degraded' ? 'badge-degraded' : 'badge-unknown';
  if (data.error) {
    return `<div class="zone-card">
      <div class="zone-header">
        <div class="zone-name">${zone}</div>
        <span class="badge ${statusCls}">${status.status || 'unknown'}</span>
      </div>
      <div class="error-card">Service unavailable</div>
    </div>`;
  }
  return `<div class="zone-card">
    <div class="zone-header">
      <div class="zone-name">${zone}</div>
      <span class="badge ${statusCls}">${status.status || 'unknown'}</span>
    </div>
    <div class="metrics">
      <div class="metric">
        <div class="metric-label">AQI</div>
        <div class="metric-value ${aqiClass(agg.avg)}">${metricValue(agg.avg)}</div>
        <div class="metric-unit">index</div>
      </div>
      <div class="metric">
        <div class="metric-label">Temperature</div>
        <div class="metric-value">${metricValue(temp.avg)}</div>
        <div class="metric-unit">°C</div>
      </div>
      <div class="metric">
        <div class="metric-label">Noise</div>
        <div class="metric-value">${metricValue(noise.avg)}</div>
        <div class="metric-unit">dB</div>
      </div>
    </div>
  </div>`;
}

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    const grid = document.getElementById('zone-grid');
    grid.innerHTML = Object.keys(d.zones).map(z =>
      renderZone(z, d.zones[z], d.statuses[z] || {status: 'unknown'})
    ).join('');
    document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error(e);
  }
}
refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    log_access(request, "dashboard")
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/api/data")
async def api_data(request: Request):
    zone_data = fetch_zone_data()
    statuses = fetch_zone_statuses()
    log_access(request, "api_data")
    return {"zones": zone_data, "statuses": statuses, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health")
async def health():
    return {"status": "ok"}
