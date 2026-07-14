# Example: full monitoring stack

An optional end-to-end demo that wires the exporter to **Prometheus** and
**Grafana**, with a provisioned diagnostic dashboard and alert rules. You don't
need this to use the exporter — it's here so you can see everything working, or
crib the dashboard/alerts into your own setup.

## Run

From this directory (it builds the exporter from `../exporter` and reads
`../.env`, so create the repo-root `.env` first — see the top-level README):

```bash
docker compose up -d --build
```

- **Grafana** → http://localhost:3000 (`admin` / `admin`) → dashboard **DSL / PPPoE Diagnostics**
- **Prometheus** → http://localhost:9090 (Alerts tab)
- **Exporter** → http://localhost:9908/metrics

## What's inside

- `prometheus/prometheus.yml` — scrapes the exporter.
- `prometheus/alerts.yml` — drop/abnormality rules: DSL re-sync, PPPoE-drop-
  while-line-up, frequent drops, low/critical SNR margin, non-`ERROR_NONE` last
  error, and more. Rules fire in Prometheus but have no notification route wired
  (no Alertmanager) — add one for paging.
- `grafana/provisioning/` — auto-configures the Prometheus datasource and loads
  the dashboard.
- `grafana/dashboards/dsl.json` — the dashboard: status tiles, the uptime-counter
  "sawtooth" panel (drops are obvious), connection-state timeline, SNR margin
  with thresholds, sync-vs-attainable rate, attenuation/power, drops-per-hour,
  and diagnostic tables.

Prometheus retains 90 days of history.

## Keeping it running 24/7

To catch intermittent drops the stack must stay up.

- **Reboots are covered:** services use `restart: unless-stopped`; enable Docker
  on boot (`sudo systemctl enable docker`).
- **On a laptop, stop it suspending** (idle or lid-close freezes the containers).
  The bulletproof, reversible fix:

  ```bash
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  # undo: sudo systemctl unmask ...
  ```

  Keep it on AC — masking blocks suspend/hibernate, not an emergency low-battery
  shutdown.
