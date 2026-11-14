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
        try:
            mbox.lock()
            locked = True
        except Exception:
            locked = False
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
            if locked:
                mbox.unlock()
    except Exception as e:
        messages.append({"id": -1, "subject": f"Error reading mailbox: {e}", "from": "", "date": "", "preview": "", "body": ""})
    messages.reverse()
    return messages


# ── Shared layout CSS (injected into both pages) ──────────────────────────────
_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --nav-bg: #1d4ed8; --sidebar-bg: #1e3a8a; --content-bg: #f1f5f9;
  --card-bg: #ffffff; --text: #1e293b; --text-muted: #64748b;
  --border: #e2e8f0; --accent: #3b82f6;
}
body { font-family: 'Montserrat', system-ui, sans-serif; font-size: 14px; background: var(--content-bg); }
.top-nav {
  position: fixed; top: 0; left: 0; right: 0; height: 64px;
  background: var(--nav-bg); display: flex; align-items: center;
  justify-content: space-between; padding: 0 24px; z-index: 100;
  box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
.nav-brand {
  display: flex; align-items: center; gap: 10px; color: #fff;
  font-size: 1rem; font-weight: 700; text-decoration: none; letter-spacing: -0.01em;
}
.nav-right { display: flex; align-items: center; gap: 20px; }
.nav-status { display: flex; align-items: center; gap: 7px; font-size: 0.75rem; color: rgba(255,255,255,0.85); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 6px #4ade80; flex-shrink: 0; }
.nav-time { font-size: 0.75rem; color: rgba(255,255,255,0.6); }
.sidebar {
  position: fixed; top: 64px; left: 0; width: 220px; height: calc(100vh - 64px);
  background: var(--sidebar-bg); display: flex; flex-direction: column;
  z-index: 90; overflow-y: auto; scrollbar-width: none;
}
.sidebar::-webkit-scrollbar { display: none; }
.sidebar-label {
  padding: 20px 20px 8px; font-size: 0.6rem; text-transform: uppercase;
  letter-spacing: 0.1em; color: rgba(255,255,255,0.4); font-weight: 600;
}
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 11px 20px;
  color: rgba(255,255,255,0.7); text-decoration: none; font-size: 0.85rem;
  font-weight: 500; border-left: 3px solid transparent; transition: all 0.15s;
}
.nav-item:hover { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.95); }
.nav-item.active { background: rgba(255,255,255,0.15); color: #fff; border-left-color: #fff; }
.nav-item svg { flex-shrink: 0; }
.nav-label { flex: 1; }
.nav-badge {
  background: #ef4444; color: #fff; border-radius: 999px;
  padding: 1px 6px; font-size: 0.65rem; font-weight: 700; min-width: 18px; text-align: center;
}
.sidebar-bottom {
  margin-top: auto; padding: 16px 20px; border-top: 1px solid rgba(255,255,255,0.1);
  font-size: 0.72rem; color: rgba(255,255,255,0.35); line-height: 1.6;
}
.content { margin-left: 220px; margin-top: 64px; padding: 28px; min-height: calc(100vh - 64px); }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; }
.page-title { font-size: 1.25rem; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 10px; }
.page-subtitle { font-size: 0.78rem; color: var(--text-muted); margin-top: 4px; font-weight: 400; }
.page-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; padding-top: 2px; }
.btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 7px;
  font-size: 0.75rem; font-weight: 600; cursor: pointer; border: none;
  transition: all 0.15s; font-family: inherit; text-decoration: none;
}
.btn-outline { background: #fff; border: 1px solid var(--border); color: var(--text-muted); }
.btn-outline:hover { border-color: var(--accent); color: var(--accent); background: #eff6ff; }
@media (max-width: 900px) {
  .sidebar { width: 60px; }
  .nav-label, .sidebar-label, .sidebar-bottom { display: none; }
  .nav-item { justify-content: center; padding: 14px; }
  .content { margin-left: 60px; }
  .nav-time { display: none; }
}
@media (max-width: 600px) {
  .sidebar { display: none; }
  .content { margin-left: 0; padding: 16px; }
}
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard — Smart City Ops</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap">
<style>
""" + _CSS + """
.zone-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 20px; }
.zone-card {
  background: var(--card-bg); border-radius: 14px; border: 1px solid var(--border);
  overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.06); transition: box-shadow 0.2s;
}
.zone-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
.zone-card-header {
  padding: 16px 20px 14px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.zone-name {
  font-size: 1rem; font-weight: 700; color: var(--text); text-transform: capitalize;
  display: flex; align-items: center; gap: 10px;
}
.zone-icon { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1rem; }
.zone-icon-north { background: #dbeafe; }
.zone-icon-center { background: #d1fae5; }
.zone-icon-south { background: #fce7f3; }
.status-pill { padding: 3px 10px; border-radius: 999px; font-size: 0.68rem; font-weight: 600; }
.pill-healthy { background: #dcfce7; color: #15803d; }
.pill-degraded { background: #fee2e2; color: #b91c1c; }
.pill-unknown { background: #f1f5f9; color: #64748b; }
.zone-card-body { padding: 16px 20px 20px; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.metric-tile { background: #f8fafc; border-radius: 10px; padding: 14px 10px; text-align: center; border: 1px solid var(--border); }
.metric-label { font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); font-weight: 600; }
.metric-value { font-size: 1.5rem; font-weight: 700; margin: 5px 0 3px; line-height: 1; }
.metric-unit { font-size: 0.65rem; color: var(--text-muted); }
.aqi-good { color: #16a34a; }
.aqi-moderate { color: #d97706; }
.aqi-unhealthy { color: #ea580c; }
.aqi-hazardous { color: #dc2626; }
.c-blue { color: #2563eb; }
.c-purple { color: #7c3aed; }
.error-state { padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.82rem; }
</style>
</head>
<body>

<header class="top-nav">
  <a class="nav-brand" href="/">
    <svg width="20" height="20" fill="none" stroke="white" stroke-width="2" viewBox="0 0 24 24">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
      <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    Smart City Ops
  </a>
  <div class="nav-right">
    <div class="nav-status">
      <span class="status-dot" id="status-dot"></span>
      <span id="service-count">Loading...</span>
    </div>
    <span class="nav-time" id="nav-time"></span>
  </div>
</header>

<aside class="sidebar">
  <div class="sidebar-label">Navigation</div>
  <a href="/" class="nav-item active">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
      <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
    </svg>
    <span class="nav-label">Dashboard</span>
  </a>
  <a href="/mail" class="nav-item">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
      <polyline points="22,6 12,13 2,6"/>
    </svg>
    <span class="nav-label">Inbox</span>
    <span class="nav-badge" id="inbox-badge" style="display:none">0</span>
  </a>
  <div class="sidebar-bottom">
    Smart City Ops<br>Environmental Monitor v1.0
  </div>
</aside>

<main class="content">
  <div class="page-header">
    <div>
      <div class="page-title">
        <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color:#3b82f6">
          <path d="M12 2a10 10 0 100 20A10 10 0 0012 2z"/><path d="M12 6v6l4 2"/>
        </svg>
        Environmental Monitor
      </div>
      <div class="page-subtitle">Real-time sensor data across all city zones &nbsp;&middot;&nbsp; auto-refresh every 10s</div>
    </div>
    <div class="page-actions">
      <a href="/api/data" target="_blank" class="btn btn-outline">
        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        Raw JSON
      </a>
    </div>
  </div>

  <div class="zone-grid" id="zone-grid">
    <div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--text-muted)">Loading zones...</div>
  </div>
</main>

<script>
var ZONE_ICONS = { north: 'N', center: 'C', south: 'S' };
var ZONE_ICON_CLS = { north: 'zone-icon-north', center: 'zone-icon-center', south: 'zone-icon-south' };

function aqiClass(v) {
  if (v == null) return 'c-blue';
  if (v <= 50) return 'aqi-good';
  if (v <= 100) return 'aqi-moderate';
  if (v <= 200) return 'aqi-unhealthy';
  return 'aqi-hazardous';
}
function fmt(v, dec) {
  dec = (dec === undefined) ? 1 : dec;
  return (v != null) ? (+v).toFixed(dec) : '—';
}
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function statusPill(s) {
  var cls = s === 'healthy' ? 'pill-healthy' : s === 'degraded' ? 'pill-degraded' : 'pill-unknown';
  return '<span class="status-pill ' + cls + '">' + esc(s || 'unknown') + '</span>';
}
function renderZone(zone, data, status) {
  var icon = ZONE_ICONS[zone] || '?';
  var iconCls = ZONE_ICON_CLS[zone] || '';
  if (data.error) {
    return '<div class="zone-card"><div class="zone-card-header"><div class="zone-name"><div class="zone-icon ' + iconCls + '">' + icon + '</div>' + esc(zone) + '</div>' + statusPill('unknown') + '</div><div class="error-state">Service unavailable</div></div>';
  }
  var agg = data.aqi || {}, temp = data.temperature_c || {}, noise = data.noise_db || {};
  return '<div class="zone-card">' +
    '<div class="zone-card-header"><div class="zone-name"><div class="zone-icon ' + iconCls + '">' + icon + '</div>' + esc(zone) + '</div>' + statusPill(status.status) + '</div>' +
    '<div class="zone-card-body"><div class="metrics">' +
      '<div class="metric-tile"><div class="metric-label">AQI</div><div class="metric-value ' + aqiClass(agg.avg) + '">' + fmt(agg.avg, 0) + '</div><div class="metric-unit">index</div></div>' +
      '<div class="metric-tile"><div class="metric-label">Temperature</div><div class="metric-value c-blue">' + fmt(temp.avg) + '</div><div class="metric-unit">°C</div></div>' +
      '<div class="metric-tile"><div class="metric-label">Noise</div><div class="metric-value c-purple">' + fmt(noise.avg, 0) + '</div><div class="metric-unit">dB</div></div>' +
    '</div></div></div>';
}
async function updateInboxBadge() {
  try {
    var r = await fetch('/api/mail');
    var d = await r.json();
    var readIds = [];
    try { readIds = JSON.parse(localStorage.getItem('sc_read_ids') || '[]'); } catch(e) {}
    var unread = (d.messages || []).filter(function(m) { return !readIds.includes(m.id); }).length;
    var badge = document.getElementById('inbox-badge');
    if (badge) { badge.textContent = unread; badge.style.display = unread > 0 ? 'inline' : 'none'; }
  } catch(e) {}
}
async function refresh() {
  try {
    var r = await fetch('/api/data');
    var d = await r.json();
    var zones = d.zones || {}, statuses = d.statuses || {};
    var grid = document.getElementById('zone-grid');
    var keys = Object.keys(zones);
    grid.innerHTML = keys.length
      ? keys.map(function(z) { return renderZone(z, zones[z], statuses[z] || {}); }).join('')
      : '<div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--text-muted)">No zone data</div>';
    var total = Object.keys(statuses).length;
    var healthy = Object.values(statuses).filter(function(s) { return s.status === 'healthy'; }).length;
    document.getElementById('service-count').textContent = healthy + '/' + total + ' zones healthy';
    var dot = document.getElementById('status-dot');
    if (dot) {
      var col = healthy === total ? '#4ade80' : '#f97316';
      dot.style.background = col; dot.style.boxShadow = '0 0 6px ' + col;
    }
    document.getElementById('nav-time').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) { console.error(e); }
}
refresh();
updateInboxBadge();
setInterval(refresh, 10000);
setInterval(updateInboxBadge, 30000);
</script>
</body>
</html>"""


MAIL_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inbox — Smart City Ops</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap">
<style>
""" + _CSS + """
.unread-chip {
  background: #ef4444; color: #fff; border-radius: 999px;
  padding: 2px 9px; font-size: 0.68rem; font-weight: 700; vertical-align: middle;
}
.mail-wrapper {
  background: var(--card-bg); border-radius: 14px; border: 1px solid var(--border);
  box-shadow: 0 1px 4px rgba(0,0,0,0.06); display: flex; overflow: hidden;
  height: calc(100vh - 240px); min-height: 400px;
}
.mail-list-pane { width: 320px; flex-shrink: 0; border-right: 1px solid var(--border); display: flex; flex-direction: column; }
.mail-list-header {
  padding: 14px 16px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  font-size: 0.8rem; font-weight: 600; color: var(--text); flex-shrink: 0;
}
.unread-count { background: var(--accent); color: #fff; border-radius: 999px; padding: 2px 8px; font-size: 0.65rem; font-weight: 700; }
.mail-list-scroll { flex: 1; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
.mail-item {
  padding: 13px 16px; border-bottom: 1px solid #f1f5f9; cursor: pointer; transition: background 0.1s;
}
.mail-item:hover { background: #f8fafc; }
.mail-item.active { background: #eff6ff; border-left: 3px solid var(--accent); padding-left: 13px; }
.mail-item-top { display: flex; align-items: center; gap: 8px; overflow: hidden; }
.unread-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
.read-spacer { width: 7px; flex-shrink: 0; }
.mail-subject { font-size: 0.82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.mail-item.unread .mail-subject { font-weight: 700; color: var(--text); }
.mail-item.read .mail-subject { font-weight: 500; color: var(--text-muted); }
.mail-from { font-size: 0.72rem; color: var(--text-muted); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mail-date { font-size: 0.68rem; color: #94a3b8; margin-top: 2px; }
.mail-preview { font-size: 0.72rem; color: #94a3b8; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mail-reader-pane { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.empty-reader { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--text-muted); gap: 12px; }
.empty-reader svg { opacity: 0.2; }
.empty-reader p { font-size: 0.85rem; }
.empty-list { padding: 32px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; }
.reader-scroll { flex: 1; overflow-y: auto; padding: 24px 28px; scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
.reader-subject { font-size: 1.1rem; font-weight: 700; color: var(--text); margin-bottom: 14px; line-height: 1.4; }
.reader-meta { background: #f8fafc; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; display: flex; flex-direction: column; gap: 5px; border: 1px solid var(--border); }
.meta-row { font-size: 0.78rem; color: var(--text-muted); }
.meta-row strong { color: var(--text); font-weight: 600; margin-right: 6px; }
.reader-divider { height: 1px; background: var(--border); margin-bottom: 16px; }
.reader-body { font-size: 0.85rem; line-height: 1.8; color: var(--text); white-space: pre-wrap; word-break: break-word; }
@media (max-width: 700px) {
  .mail-list-pane { width: 100%; border-right: none; }
  .mail-reader-pane { display: none; }
}
</style>
</head>
<body>

<header class="top-nav">
  <a class="nav-brand" href="/">
    <svg width="20" height="20" fill="none" stroke="white" stroke-width="2" viewBox="0 0 24 24">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
      <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    Smart City Ops
  </a>
  <div class="nav-right">
    <div class="nav-status">
      <span class="status-dot"></span>
      <span>Operator Inbox</span>
    </div>
    <span class="nav-time" id="nav-time"></span>
  </div>
</header>

<aside class="sidebar">
  <div class="sidebar-label">Navigation</div>
  <a href="/" class="nav-item">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
      <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
    </svg>
    <span class="nav-label">Dashboard</span>
  </a>
  <a href="/mail" class="nav-item active">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
      <polyline points="22,6 12,13 2,6"/>
    </svg>
    <span class="nav-label">Inbox</span>
    <span class="nav-badge" id="inbox-badge" style="display:none">0</span>
  </a>
  <div class="sidebar-bottom">
    Smart City Ops<br>Environmental Monitor v1.0
  </div>
</aside>

<main class="content">
  <div class="page-header">
    <div>
      <div class="page-title">
        <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="color:#3b82f6">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
          <polyline points="22,6 12,13 2,6"/>
        </svg>
        Operator Inbox
        <span class="unread-chip" id="unread-chip" style="display:none">0</span>
      </div>
      <div class="page-subtitle">Alert notifications and system messages</div>
    </div>
    <div class="page-actions">
      <button class="btn btn-outline" onclick="loadMail()">
        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>
  </div>

  <div class="mail-wrapper">
    <div class="mail-list-pane">
      <div class="mail-list-header">
        <span>Inbox</span>
        <span class="unread-count" id="count-badge">0</span>
      </div>
      <div class="mail-list-scroll" id="mail-list">
        <div class="empty-list">Loading...</div>
      </div>
    </div>
    <div class="mail-reader-pane" id="mail-reader">
      <div class="empty-reader">
        <svg width="52" height="52" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
          <path d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/>
        </svg>
        <p>Select a message to read</p>
      </div>
    </div>
  </div>
</main>

<script>
var allMail = [];
var readIds = new Set();
try { readIds = new Set(JSON.parse(localStorage.getItem('sc_read_ids') || '[]')); } catch(e) {}

function saveReadIds() {
  try { localStorage.setItem('sc_read_ids', JSON.stringify([...readIds])); } catch(e) {}
}
function countUnread(msgs) {
  return msgs.filter(function(m) { return !readIds.has(m.id); }).length;
}
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtDate(d) {
  if (!d) return '';
  try { return new Date(d).toLocaleString(); } catch(e) { return String(d); }
}
function updateBadges(msgs) {
  var unread = countUnread(msgs);
  var cb = document.getElementById('count-badge');
  var chip = document.getElementById('unread-chip');
  var sb = document.getElementById('inbox-badge');
  if (cb) cb.textContent = unread;
  if (chip) { chip.textContent = unread; chip.style.display = unread > 0 ? 'inline' : 'none'; }
  if (sb) { sb.textContent = unread; sb.style.display = unread > 0 ? 'inline' : 'none'; }
}
function renderList(msgs) {
  updateBadges(msgs);
  var el = document.getElementById('mail-list');
  if (!msgs.length) { el.innerHTML = '<div class="empty-list">No messages yet.</div>'; return; }
  el.innerHTML = msgs.map(function(m, i) {
    var isRead = readIds.has(m.id);
    return '<div class="mail-item ' + (isRead ? 'read' : 'unread') + '" id="item-' + i + '" onclick="openMail(' + i + ')">' +
      '<div class="mail-item-top">' +
        (isRead ? '<span class="read-spacer"></span>' : '<span class="unread-dot"></span>') +
        '<span class="mail-subject">' + esc(m.subject) + '</span>' +
      '</div>' +
      '<div class="mail-from">' + esc(m.from) + '</div>' +
      '<div class="mail-date">' + fmtDate(m.date) + '</div>' +
      '<div class="mail-preview">' + esc(m.preview) + '</div>' +
    '</div>';
  }).join('');
}
function openMail(idx) {
  document.querySelectorAll('.mail-item').forEach(function(el) { el.classList.remove('active'); });
  var itemEl = document.getElementById('item-' + idx);
  if (itemEl) itemEl.classList.add('active');
  var m = allMail[idx];
  if (!m) return;
  if (!readIds.has(m.id)) {
    readIds.add(m.id);
    saveReadIds();
    if (itemEl) {
      itemEl.classList.remove('unread');
      itemEl.classList.add('read');
      var dot = itemEl.querySelector('.unread-dot');
      if (dot) { dot.className = 'read-spacer'; }
    }
    updateBadges(allMail);
  }
  document.getElementById('mail-reader').innerHTML =
    '<div class="reader-scroll">' +
      '<div class="reader-subject">' + esc(m.subject) + '</div>' +
      '<div class="reader-meta">' +
        '<div class="meta-row"><strong>From:</strong>' + esc(m.from) + '</div>' +
        '<div class="meta-row"><strong>Date:</strong>' + fmtDate(m.date) + '</div>' +
      '</div>' +
      '<div class="reader-divider"></div>' +
      '<div class="reader-body">' + esc(m.body || '(empty)') + '</div>' +
    '</div>';
}
async function loadMail() {
  try {
    var r = await fetch('/api/mail');
    var d = await r.json();
    var msgs = d.messages || [];
    var lastCount = parseInt(localStorage.getItem('sc_last_count') || '0');
    if (msgs.length < lastCount - 3) { readIds.clear(); saveReadIds(); }
    try { localStorage.setItem('sc_last_count', String(msgs.length)); } catch(e) {}
    allMail = msgs;
    renderList(allMail);
    document.getElementById('nav-time').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById('mail-list').innerHTML = '<div class="empty-list">Failed to load.</div>';
  }
}
loadMail();
setInterval(loadMail, 30000);
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
