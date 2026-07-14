# TP-Link DSL router monitoring

Monitors a TP-Link DSL modem/router over its telnet CLI and graphs the DSL line
and PPPoE session over time, so you can catch *when* the connection drops and,
more importantly, *which layer* dropped — the copper line or the PPPoE session.

Stack: a small Python exporter → Prometheus (storage + alerting) → Grafana
(dashboard), all in Docker Compose.

```
router (telnet CLI) ──► exporter :9908 ──► Prometheus :9090 ──► Grafana :3000
```

## Quick start

```bash
cp .env.example .env      # already present; edit if your password isn't "admin"
docker compose up -d --build
```

Then open:

- **Grafana**: http://localhost:3000  (login `admin` / `admin`) → dashboard **DSL / PPPoE Diagnostics**
- **Prometheus**: http://localhost:9090  (try Alerts tab)
- **Raw metrics**: http://localhost:9908/metrics

Let it collect for a few hours (ideally across a drop or two) before drawing
conclusions.

## How this diagnoses the drops

This firmware's telnet CLI does **not** expose CRC/FEC/errored-second counters,
so the strategy is built around the two uptime counters it *does* expose, plus
the line-quality figures:

| Metric | What it tells you |
| --- | --- |
| `dsl_line_uptime_seconds` | Seconds since the **DSL line** last synced. Resets to ~0 on every re-train. |
| `pppoe_uptime_seconds` | Seconds since the **PPPoE session** last connected. Resets to ~0 on every session drop. |

Watch the **"Uptime counters"** panel — each series climbs steadily and drops to
zero on an event (a sawtooth). The pattern of the two sawtooths is the diagnosis:

- **Both reset at the same time** → the DSL modem lost sync (re-train). This is a
  **line / layer-1** problem: noise, low SNR margin, bad wiring, a faulty
  microfilter, or interference. Look at `dsl_downstream_snr_margin_db` just
  before the event — a margin sliding toward/below 6 dB is the culprit.
  Alert: `DSLResync`, `FrequentDSLResyncs`, `LowDownstreamSNRMargin`.

- **PPPoE resets but the DSL line uptime keeps climbing** → the copper line was
  fine and only the **PPPoE session** dropped. This is your suspected
  misconfiguration / ISP-side signature: LCP keepalive, idle timeout, MTU/MRU,
  auth, or the ISP resetting the session. Check `pppoe_last_connection_error_info`.
  Alert: `PPPoEDropWhileLineUp`, `FrequentPPPoEDrops`.

That single distinction is what tells you whether to chase the phone line or the
PPPoE config.

### PPPoE config values surfaced for the misconfig hunt

The dashboard shows these read straight from `wan show connection info`:

- **LCP echo retry** (`pppoe_lcp_echo_retry`) — **0 on your router right now.**
  With zero retries the router can tear the session down on a single missed
  keepalive (or, conversely, fail to notice a half-dead session). If you see
  `PPPoEDropWhileLineUp` events, this is the prime suspect. Alert:
  `PPPoELCPEchoRetryDisabled`.
- **LCP echo interval** (`pppoe_lcp_echo_interval_seconds`), **idle disconnect**
  (`pppoe_idle_disconnect_time`), and the connection trigger (in the details
  table) — an idle timeout with an "AlwaysOn" trigger is contradictory and worth
  a look.

### Baseline captured on first run

For reference, the line looked healthy at deploy time: ADSL2+, downstream sync
~8.8 Mbps against ~9.9 Mbps attainable, downstream SNR margin ~9.4 dB (healthy is
≥6, comfortable ≥9), upstream margin ~14.5 dB, moderate attenuation. The last
event before deploy was a full DSL re-sync (both uptimes matched), and
`lastConnectionError` was `ERROR_NONE`. So at that instant nothing was wrong —
which is exactly why continuous monitoring is needed to catch the intermittent
drops in the act.

## What gets scraped

Every `SCRAPE_INTERVAL` (default 20s) the exporter logs into the CLI and runs:

- `adsl show info` → line status, sync/attainable rates, SNR margin, attenuation,
  transmit power, sync uptime, bitswap/SRA, modulation/profile.
- `wan show connection info` → PPPoE status, session uptime, last error, session
  id, and the LCP/idle config above.

### Metrics reference (prefix `dsl_` / `pppoe_`)

Availability: `dsl_up`, `dsl_scrape_duration_seconds`, `dsl_scrape_errors_total`,
`dsl_reconnects_total`.
Line: `dsl_line_status`, `dsl_downstream_rate_kbps`, `dsl_upstream_rate_kbps`,
`dsl_downstream_max_rate_kbps`, `dsl_upstream_max_rate_kbps`,
`dsl_downstream_snr_margin_db`, `dsl_upstream_snr_margin_db`,
`dsl_downstream_attenuation_db`, `dsl_upstream_attenuation_db`,
`dsl_downstream_power_dbm`, `dsl_upstream_power_dbm`, `dsl_line_uptime_seconds`,
`dsl_bitswap_enabled`, `dsl_sra_enabled`, `dsl_line_info{...}`.
PPPoE: `pppoe_connection_status`, `pppoe_uptime_seconds`,
`pppoe_last_connection_error_info{error=...}`, `pppoe_lcp_echo_interval_seconds`,
`pppoe_lcp_echo_retry`, `pppoe_idle_disconnect_time`, `pppoe_session_id`,
`pppoe_connection_info{...}`.

## Alerts

Rules live in `prometheus/alerts.yml` and show up under Prometheus → Alerts. They
fire in Prometheus but have **no notification route wired** (no Alertmanager) —
this is a diagnosis tool, not a paging setup. To get emails/Slack, add an
Alertmanager service and a `alerting:` block in `prometheus.yml`.

Covered: exporter down, line down, PPPoE down, DSL re-sync, PPPoE-drop-while-line-up,
frequent re-syncs, frequent PPPoE drops, low/critical SNR margin, sync far below
attainable, non-NONE last error, and the LCP-echo-retry-disabled config hint.

## Security notes

- `.env` holds the router password and is git-ignored.
- The router's `wan show connection info` prints the **PPPoE username and password
  in clear text**. The exporter drops those fields during parsing and never
  exports or logs them — verify with `curl -s localhost:9908/metrics | grep -i pass`
  (returns nothing).
- Telnet is unauthenticated/clear-text on the LAN; that's a router limitation, not
  something the exporter can fix. Keep the stack on a trusted network.

## Configuration

All via `.env` (see `.env.example`): `ROUTER_HOST`, `ROUTER_TELNET_PORT`,
`ROUTER_PASSWORD`, `ROUTER_USERNAME` (blank = password-only login on this model),
`SCRAPE_INTERVAL`, `LOG_LEVEL`, `GRAFANA_USER`, `GRAFANA_PASSWORD`.

Prometheus retains 90 days of history (`docker-compose.yml`).

## Keeping it running 24/7

To catch intermittent drops the stack has to stay up continuously.

- **Reboots are covered.** All services use `restart: unless-stopped` and Docker
  is enabled on boot, so after a reboot or crash the stack comes back on its own.
- **The router recycles idle telnet sessions.** This is normal for these models —
  it shows up as `Connection reset by peer`. The exporter handles it by
  reconnecting and retrying within the same scrape cycle, so it doesn't leave a
  gap; these recoveries are counted in `dsl_reconnects_total` (benign), separate
  from `dsl_scrape_errors_total` (a scrape that failed even after a retry).
- **On a laptop, stop it from suspending.** If the machine suspends (idle or lid
  close) the containers freeze with it. The bulletproof, reversible fix is to
  mask the sleep targets:

  ```bash
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  # undo with: sudo systemctl unmask ...
  ```

  Keep the laptop on AC power — masking blocks suspend/hibernate, but a critically
  low battery can still force a shutdown.

## Running the exporter without Docker

It's a self-contained [uv](https://docs.astral.sh/uv/) script with inline
dependencies:

```bash
cd exporter
ROUTER_PASSWORD=admin uv run exporter.py
```

## Troubleshooting

- `docker logs dsl-exporter` — should say "logged in to router CLI". `dsl_up 0`
  means the login/telnet failed (wrong password, telnet disabled, or the router
  only allows one telnet session at a time — close other sessions).
- Only one telnet session may be allowed at once; if you telnet in manually the
  exporter's scrape can fail until you log out.
- No data in Grafana panels → check Prometheus → Status → Targets shows
  `dsl-exporter` **UP**.
