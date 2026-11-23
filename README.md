# Smart City SOA - Security Monitoring Platform

SSLE Project 1 - Master's in Cybersecurity - DETI, University of Aveiro - 2026

Security monitoring and active-response platform for a Smart City Environmental
Monitoring system. Three geographic zones (North, Centre, South) each run a zone
aggregator edge service. A central SOA stack handles ingestion, storage, analytics,
alerting, and an operator portal. Wazuh detects threats via 13 custom rules;
automated IP blocking is applied through a custom threat-blocker service.

## Prerequisites

- Debian/Ubuntu host with **Incus** already installed and initialised
- `git`, `python3` available on the host
- ~6 GB RAM free for containers (smartcity-services: 3 GB, wazuh: ~3 GB)

## Setup (first time only)

```bash
bash scripts/setup_incus.sh
```

Creates and configures three Incus containers (`smartcity-services`, `wazuh`,
`attacker`), installs Docker inside `smartcity-services`, pushes all project
files, generates `.env`, and configures the Wazuh agent.

What the script does automatically:
- Loads the `br_netfilter` kernel module (required for Docker with `userland-proxy=false`)
- Creates shared log directories on the host and mounts them into both containers
- Extracts the Wazuh auto-generated password and writes it to `.env`
- Installs `hey` (HTTP load generator) on the host

Takes ~15–20 minutes. If the Wazuh password extraction fails, retrieve it manually:

```bash
incus exec wazuh -- cat /tmp/wazuh-install-files/wazuh-passwords.txt
```

Then update `WAZUH_PASS` in `.env`.

## Start / Stop

```bash
bash scripts/run_all.sh     # start Wazuh + all Docker services
bash scripts/stop_all.sh    # stop Docker services + Wazuh container
```

Find container IPs:

```bash
incus list
```

After `run_all.sh`, access:

| Service        | URL                                           | Credentials      |
|----------------|-----------------------------------------------|------------------|
| Ops portal     | `http://<smartcity-ip>:5600`                  | —                |
| Grafana        | `http://<smartcity-ip>:3000`                  | admin / admin    |
| Prometheus     | `http://<smartcity-ip>:9090`                  | —                |
| Wazuh UI       | `https://<wazuh-ip>`                          | admin / printed during Wazuh install step |
| Wazuh API      | `https://<wazuh-ip>:55000`                    | wazuh / `WAZUH_PASS` in `.env`   |

> Wazuh uses a self-signed certificate (accept the browser warning).

## Reset (between demo runs)

```bash
bash scripts/reset_all.sh
```

Wipes Wazuh OpenSearch indices, Docker volumes, and all log files. Required
before each clean demo run to ensure counters start from zero.

## Demos

Each script should be run from the host (Debian VM). Run `reset_all.sh` before each demo.

| Threat                | Script                          | Notes                                      |
|-----------------------|---------------------------------|--------------------------------------------|
| HTTP Flood (DoS)      | `bash scripts/demo_dos.sh`      | —                                          |
| Botnet DDoS           | `bash scripts/demo_botnet.sh [N]` | default N=3 bots                         |
| APT (Recon+Honeypot)  | `bash scripts/demo_apt.sh [--zone north\|center\|south]` | extracts INTERNAL_TOKEN |
| Alert Email Flooding  | `bash scripts/demo_spam.sh`     | requires APT demo to have run first        |
| Drug Content Spam     | `bash scripts/demo_drug_spam.sh` | —                                         |

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
report/             # LaTeX source
```
