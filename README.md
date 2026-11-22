# Smart City SOA - Security Monitoring Platform

SSLE Project 1 - Master's in Cybersecurity - DETI, University of Aveiro - 2026

Security monitoring and active-response platform for a Smart City Environmental
Monitoring system. Three geographic zones (North, Centre, South) each run a zone
aggregator edge service. A central SOA stack handles ingestion, storage, analytics,
alerting, and an operator portal. Wazuh detects threats via 13 custom rules;
automated IP blocking is applied through a custom threat-blocker service.

## Setup (first time only)

```bash
bash scripts/setup_incus.sh
```

Creates and configures three Incus containers (`smartcity-services`, `wazuh`,
`attacker`), installs Docker inside `smartcity-services`, pushes all project
files, generates `.env`, and configures the Wazuh agent. Takes ~15–20 minutes.

## Start / Stop

```bash
bash scripts/run_all.sh     # start Wazuh + all Docker services
bash scripts/stop_all.sh    # stop Docker services + Wazuh container
```

After `run_all.sh`, access:

| Service     | URL                                      |
|-------------|------------------------------------------|
| Ops portal  | `http://<smartcity-ip>:5600`             |
| Grafana     | `http://<smartcity-ip>:3000`  (admin/admin) |
| Prometheus  | `http://<smartcity-ip>:9090`             |

The `smartcity-services` IP is shown by `incus list`.

## Reset (between demo runs)

```bash
bash scripts/reset_all.sh
```

Wipes Wazuh OpenSearch indices, Docker volumes, and all log files. Required
before each clean demo run to ensure counters start from zero.

## Demos

Each script should be run from the Debian VM. Run `reset_all.sh` before each demo.

| Threat | Script | Notes |
|--------|--------|-------|
| HTTP Flood (DoS) | `bash scripts/demo_dos.sh` | — |
| Botnet DDoS | `bash scripts/demo_botnet.sh [N]` | default N=3 bots |
| APT (Recon + Honeypot) | `bash scripts/demo_apt.sh [--zone north\|center\|south]` | extracts INTERNAL_TOKEN |
| Alert Email Flooding | `bash scripts/demo_spam.sh` | requires APT demo to have run first |
| Drug Content Spam | `bash scripts/demo_drug_spam.sh` | — |

## Utilities

```bash
bash scripts/unblock_ips.sh       # manually clear all iptables blocks
bash scripts/clear_wazuh_logs.sh  # delete Wazuh OpenSearch indices only
bash scripts/teardown_incus.sh    # destroy all containers (full reset)
```

## Project Structure

```
services/           # FastAPI microservices (zone aggregators, ingestion, etc.)
monitoring/         # Prometheus config, Grafana dashboards, Wazuh rules
poc/                # Attack scripts (run inside attacker container)
scripts/            # Setup, run, reset, and demo scripts
report/             # LaTeX source for the project report
```
