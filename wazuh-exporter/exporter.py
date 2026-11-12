"""
Wazuh Prometheus exporter.
Reads /var/ossec/logs/alerts/alerts.json and polls Wazuh REST API.
Exposes metrics on :9100/metrics.
"""
import os
import json
import time
import threading
import logging
from collections import defaultdict

import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import (
    Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
)

WAZUH_HOST = os.getenv("WAZUH_HOST", "wazuh-manager")
WAZUH_PORT = os.getenv("WAZUH_PORT", "55000")
WAZUH_USER = os.getenv("WAZUH_USER", "wazuh")
WAZUH_PASS = os.getenv("WAZUH_PASS", "wazuh")
ALERTS_JSON = os.getenv("ALERTS_JSON", "/var/ossec/logs/alerts/alerts.json")
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9100"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))

registry = CollectorRegistry()

wazuh_up = Gauge("wazuh_up", "1 if Wazuh API is reachable", registry=registry)
wazuh_agents_total = Gauge("wazuh_agents_total", "Total registered Wazuh agents", registry=registry)
wazuh_agents_active = Gauge("wazuh_agents_active", "Active Wazuh agents", registry=registry)
wazuh_agents_disconnected = Gauge("wazuh_agents_disconnected", "Disconnected Wazuh agents", registry=registry)
wazuh_manager_status = Gauge(
    "wazuh_manager_status", "Wazuh daemon status (1=running)",
    ["daemon"], registry=registry
)
wazuh_alerts_total = Counter(
    "wazuh_alerts_total", "Total Wazuh alerts processed",
    ["level", "rule_id", "description", "client_ip", "zone"], registry=registry
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wazuh-exporter")

_jwt_token = None
_token_lock = threading.Lock()


def get_jwt():
    global _jwt_token
    try:
        resp = requests.post(
            f"https://{WAZUH_HOST}:{WAZUH_PORT}/security/user/authenticate",
            auth=(WAZUH_USER, WAZUH_PASS),
            verify=False,
            timeout=10,
        )
        if resp.status_code == 200:
            _jwt_token = resp.json()["data"]["token"]
    except Exception as e:
        log.warning(f"JWT fetch failed: {e}")


def api_get(path: str):
    with _token_lock:
        if not _jwt_token:
            get_jwt()
        token = _jwt_token
    try:
        resp = requests.get(
            f"https://{WAZUH_HOST}:{WAZUH_PORT}{path}",
            headers={"Authorization": f"Bearer {token}"},
            verify=False,
            timeout=10,
        )
        if resp.status_code == 401:
            get_jwt()
            return None
        return resp.json()
    except Exception as e:
        log.warning(f"API GET {path} failed: {e}")
        return None


def poll_api():
    data = api_get("/agents/summary/status")
    if data and data.get("data"):
        summary = data["data"].get("connection", {})
        wazuh_agents_total.set(sum(summary.values()))
        wazuh_agents_active.set(summary.get("active", 0))
        wazuh_agents_disconnected.set(summary.get("disconnected", 0))
        wazuh_up.set(1)
    else:
        wazuh_up.set(0)

    mgr = api_get("/manager/status")
    if mgr and mgr.get("data"):
        items = mgr["data"].get("affected_items", [])
        daemons = items[0] if items else mgr["data"].get("daemons", {})
        for daemon, status in daemons.items():
            wazuh_manager_status.labels(daemon=daemon).set(1 if status == "running" else 0)


_alerts_pos = 0


def tail_alerts():
    global _alerts_pos
    if not os.path.exists(ALERTS_JSON):
        return
    try:
        with open(ALERTS_JSON, "r") as f:
            f.seek(_alerts_pos)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    alert = json.loads(line)
                    rule = alert.get("rule", {})
                    level = str(rule.get("level", "0"))
                    rule_id = str(rule.get("id", "0"))
                    description = rule.get("description", "")[:64]
                    data = alert.get("data", {})
                    client_ip = data.get("client_ip", data.get("srcip", "unknown"))
                    zone = data.get("zone", "unknown")
                    wazuh_alerts_total.labels(
                        level=level, rule_id=rule_id,
                        description=description,
                        client_ip=client_ip, zone=zone,
                    ).inc()
                except json.JSONDecodeError:
                    pass
            _alerts_pos = f.tell()
    except Exception as e:
        log.warning(f"Alert tail failed: {e}")


def collect_loop():
    get_jwt()
    while True:
        poll_api()
        tail_alerts()
        time.sleep(POLL_INTERVAL)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            output = generate_latest(registry)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(output)
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=collect_loop, daemon=True).start()
    log.info(f"Wazuh exporter running on :{EXPORTER_PORT}")
    HTTPServer(("0.0.0.0", EXPORTER_PORT), MetricsHandler).serve_forever()
