import os
import json
import logging
import mailbox
import email.header
import email.utils
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from prometheus_fastapi_instrumentator import Instrumentator

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://service-registry:5050")
ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://analytics-service:5400")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "changeme")
PORT = int(os.getenv("PORT", "5600"))
MBOX_PATH = os.getenv("MBOX_PATH", "/var/mail/smartcity.local/operator")

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


def _decode_header(value: str) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for fragment, charset in parts:
        if isinstance(fragment, bytes):
            out.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(fragment)
    return "".join(out)


def _get_text_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace") if payload else ""
        return ""
    payload = msg.get_payload(decode=True)
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace") if payload else ""


def read_mailbox():
    messages = []
    if not os.path.exists(MBOX_PATH):
        return messages
    try:
        mbox = mailbox.mbox(MBOX_PATH, create=False)
        mbox.lock()
        try:
            for i, msg in enumerate(mbox):
                subject = _decode_header(msg.get("Subject", "(no subject)"))
                from_addr = _decode_header(msg.get("From", "unknown"))
                date_str = msg.get("Date", "")
                try:
                    date_parsed = email.utils.parsedate_to_datetime(date_str).isoformat()
                except Exception:
                    date_parsed = date_str
                body = _get_text_body(msg)
                messages.append({
                    "id": i,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_parsed,
                    "preview": body[:160].replace("\n", " "),
                    "body": body,
                })
        finally:
            mbox.unlock()
    except Exception as e:
        messages.append({"id": -1, "subject": f"Error reading mailbox: {e}", "from": "", "date": "", "preview": "", "body": ""})
    messages.reverse()
    return messages


MAIL_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operator Inbox — Smart City</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; }
  header { background: #1e293b; padding: 0.8rem 1.5rem; border-bottom: 1px solid #334155;
           display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
  header h1 { font-size: 1.1rem; font-weight: 600; color: #38bdf8; }
  header nav a { font-size: 0.8rem; color: #94a3b8; text-decoration: none; margin-left: 1rem; }
  header nav a:hover { color: #38bdf8; }
  .layout { display: flex; flex: 1; overflow: hidden; }
  .sidebar { width: 340px; flex-shrink: 0; border-right: 1px solid #334155; overflow-y: auto; }
  .sidebar-header { padding: 0.75rem 1rem; border-bottom: 1px solid #1e293b; display: flex; align-items: center; justify-content: space-between; }
  .sidebar-header span { font-size: 0.75rem; color: #64748b; }
  .msg-count { background: #38bdf8; color: #0f172a; border-radius: 999px; padding: 0.1rem 0.5rem; font-size: 0.7rem; font-weight: 700; }
  .mail-item { padding: 0.85rem 1rem; border-bottom: 1px solid #1e293b; cursor: pointer; transition: background 0.15s; }
  .mail-item:hover { background: #1e293b; }
  .mail-item.active { background: #172554; border-left: 3px solid #38bdf8; }
  .mail-subject { font-size: 0.85rem; font-weight: 600; color: #e2e8f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mail-from { font-size: 0.75rem; color: #94a3b8; margin-top: 0.2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mail-date { font-size: 0.7rem; color: #475569; margin-top: 0.15rem; }
  .mail-preview { font-size: 0.72rem; color: #64748b; margin-top: 0.3rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .content { flex: 1; overflow-y: auto; padding: 1.5rem 2rem; }
  .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #475569; gap: 0.5rem; }
  .empty-state svg { opacity: 0.3; }
  .msg-header { margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid #334155; }
  .msg-title { font-size: 1.15rem; font-weight: 600; color: #f1f5f9; margin-bottom: 0.6rem; }
  .msg-meta { display: flex; flex-direction: column; gap: 0.25rem; }
  .msg-meta-row { font-size: 0.8rem; color: #94a3b8; }
  .msg-meta-row strong { color: #64748b; }
  .msg-body { font-size: 0.85rem; line-height: 1.7; color: #cbd5e1; white-space: pre-wrap; word-break: break-word; }
  .no-mail { text-align: center; padding: 2rem; color: #475569; font-size: 0.85rem; }
  .refresh-btn { font-size: 0.75rem; color: #38bdf8; background: none; border: 1px solid #334155; border-radius: 6px; padding: 0.2rem 0.6rem; cursor: pointer; }
  .refresh-btn:hover { background: #1e293b; }
  @media (max-width: 640px) {
    .layout { flex-direction: column; }
    .sidebar { width: 100%; max-height: 40vh; }
  }
</style>
</head>
<body>
<header>
  <h1>&#128231; Operator Inbox</h1>
  <nav>
    <a href="/">&#8592; Dashboard</a>
    <button class="refresh-btn" onclick="loadMail()">&#8635; Refresh</button>
  </nav>
</header>
<div class="layout">
  <div class="sidebar">
    <div class="sidebar-header">
      <span>Inbox</span>
      <span class="msg-count" id="count">0</span>
    </div>
    <div id="mail-list"><div class="no-mail">Loading...</div></div>
  </div>
  <div class="content" id="content">
    <div class="empty-state">
      <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/>
      </svg>
      <p>Select an email to read it</p>
    </div>
  </div>
</div>
<script>
let allMail = [];

function fmtDate(d) {
  if (!d) return '';
  try { return new Date(d).toLocaleString(); } catch { return d; }
}

function renderList(msgs) {
  const el = document.getElementById('mail-list');
  document.getElementById('count').textContent = msgs.length;
  if (!msgs.length) { el.innerHTML = '<div class="no-mail">No messages yet.</div>'; return; }
  el.innerHTML = msgs.map((m, i) => `
    <div class="mail-item" id="item-${i}" onclick="openMail(${i})">
      <div class="mail-subject">${esc(m.subject)}</div>
      <div class="mail-from">${esc(m.from)}</div>
      <div class="mail-date">${fmtDate(m.date)}</div>
      <div class="mail-preview">${esc(m.preview)}</div>
    </div>`).join('');
}

function openMail(idx) {
  document.querySelectorAll('.mail-item').forEach(el => el.classList.remove('active'));
  const item = document.getElementById('item-' + idx);
  if (item) item.classList.add('active');
  const m = allMail[idx];
  if (!m) return;
  document.getElementById('content').innerHTML = `
    <div class="msg-header">
      <div class="msg-title">${esc(m.subject)}</div>
      <div class="msg-meta">
        <div class="msg-meta-row"><strong>From:</strong> ${esc(m.from)}</div>
        <div class="msg-meta-row"><strong>Date:</strong> ${fmtDate(m.date)}</div>
      </div>
    </div>
    <div class="msg-body">${esc(m.body || '(empty)')}</div>`;
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadMail() {
  try {
    const r = await fetch('/api/mail');
    const d = await r.json();
    allMail = d.messages || [];
    renderList(allMail);
  } catch(e) {
    document.getElementById('mail-list').innerHTML = '<div class="no-mail">Failed to load mail.</div>';
  }
}

loadMail();
setInterval(loadMail, 30000);
</script>
</body>
</html>"""


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
  <div class="refresh-bar">Auto-refresh every 10s &nbsp;|&nbsp; <a href="/api/data" style="color:#38bdf8">Raw JSON</a> &nbsp;|&nbsp; <a href="/mail" style="color:#38bdf8">&#128231; Operator Inbox</a></div>
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


@app.get("/mail", response_class=HTMLResponse)
async def mail_viewer(request: Request):
    log_access(request, "mail_viewer")
    return HTMLResponse(content=MAIL_VIEWER_HTML)


@app.get("/api/mail")
async def api_mail(request: Request):
    log_access(request, "api_mail")
    messages = read_mailbox()
    return {"messages": messages, "count": len(messages)}


@app.get("/health")
async def health():
    return {"status": "ok"}
