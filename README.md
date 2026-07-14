# tplink-dsl-exporter

[![CI](https://github.com/sergiombd/tplink-dsl-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/sergiombd/tplink-dsl-exporter/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/sergiombd/tplink-dsl-exporter?sort=semver)](https://github.com/sergiombd/tplink-dsl-exporter/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Prometheus exporter for TP-Link DSL modem/routers (Archer VR-series and
similar) that expose only a **telnet CLI**. It logs in over telnet, scrapes the
DSL line and PPPoE/WAN status, and serves them at `/metrics` — so you can graph
your line over time and, in particular, catch and characterise intermittent
disconnects.

Tested against an **Archer VR300** (password-only telnet CLI, prompt
`TP-Link(conf)#`).

## Why

These routers don't expose SNMP or a metrics endpoint, and their firmware
doesn't surface CRC/FEC/errored-second counters at all. But the telnet CLI does
expose two uptime counters that, together, tell you *which layer* dropped:

| Metric | Resets when… |
| --- | --- |
| `dsl_line_uptime_seconds` | the **DSL line** re-syncs (layer 1 — copper/noise) |
| `pppoe_uptime_seconds` | the **PPPoE session** drops (layer 2/3 — ISP/keepalive/config) |

- Both reset together → a DSL re-train (line quality: noise, low SNR margin, wiring).
- Only PPPoE resets while the line stays up → a PPPoE/ISP/config problem.

That single distinction is usually enough to know whether to chase the phone
line or the PPPoE setup.

## Run it

**Prebuilt image (easiest — no clone needed):**

```bash
docker run -d --name dsl-exporter -p 9908:9908 \
  -e ROUTER_HOST=192.168.1.1 -e ROUTER_PASSWORD=admin \
  ghcr.io/sergiombd/tplink-dsl-exporter:latest
```

Images are published to GHCR for `linux/amd64` and `linux/arm64` (so it runs on
a Raspberry Pi next to your router). Pin a release with `:v0.1.0` instead of
`:latest`.

---

If you'd rather build from source, the exporter needs a `.env` with your
router's telnet password:

```bash
cp .env.example .env      # then edit ROUTER_PASSWORD / ROUTER_HOST
```

**With Docker Compose (exporter only):**

```bash
docker compose up -d --build
curl -s localhost:9908/metrics | grep '^dsl_'
```

**With Docker directly:**

```bash
docker build -t dsl-exporter ./exporter
docker run -d --name dsl-exporter -p 9908:9908 \
  -e ROUTER_HOST=192.168.1.1 -e ROUTER_PASSWORD=admin \
  dsl-exporter
```

**Standalone** (it's a self-contained [uv](https://docs.astral.sh/uv/) script
with inline dependencies — no venv setup needed):

```bash
cd exporter
ROUTER_PASSWORD=admin uv run exporter.py
```

Then point Prometheus at it:

```yaml
scrape_configs:
  - job_name: dsl
    static_configs:
      - targets: ["localhost:9908"]
```

Want the whole thing wired up with Prometheus, Grafana, a provisioned
diagnostic dashboard and alert rules? See [`example/`](example/).

## Configuration

All via environment variables (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ROUTER_HOST` | `192.168.1.1` | Router address |
| `ROUTER_TELNET_PORT` | `23` | Telnet port |
| `ROUTER_PASSWORD` | `admin` | Telnet password |
| `ROUTER_USERNAME` | *(blank)* | Set only if your model asks for a username too |
| `SCRAPE_INTERVAL` | `20` | Seconds between logins/refreshes |
| `EXPORTER_PORT` | `9908` | Port `/metrics` is served on |
| `LOG_LEVEL` | `INFO` | `DEBUG` for per-scrape detail |

## Metrics

**Availability:** `dsl_up`, `dsl_scrape_duration_seconds`,
`dsl_scrape_errors_total`, `dsl_reconnects_total`,
`dsl_exporter_build_info{version}`.

**DSL line** (`adsl show info`): `dsl_line_status`,
`dsl_downstream_rate_kbps`, `dsl_upstream_rate_kbps`,
`dsl_downstream_max_rate_kbps`, `dsl_upstream_max_rate_kbps`,
`dsl_downstream_snr_margin_db`, `dsl_upstream_snr_margin_db`,
`dsl_downstream_attenuation_db`, `dsl_upstream_attenuation_db`,
`dsl_downstream_power_dbm`, `dsl_upstream_power_dbm`,
`dsl_line_uptime_seconds`, `dsl_bitswap_enabled`, `dsl_sra_enabled`,
`dsl_line_info{modulation,profile,annex,datapath,encapsulation}`.

**PPPoE / WAN** (`wan show connection info`): `pppoe_connection_status`,
`pppoe_uptime_seconds`, `pppoe_last_connection_error_info{error}`,
`pppoe_lcp_echo_interval_seconds`, `pppoe_lcp_echo_retry`,
`pppoe_idle_disconnect_time`, `pppoe_session_id`,
`pppoe_connection_info{interface,external_ip,remote_ip,gateway,server_mac,...}`.

## Notes & caveats

- **Credentials are never exported.** The router's `wan show connection info`
  prints the PPPoE username and password in clear text; the exporter drops those
  fields during parsing. Verify with
  `curl -s localhost:9908/metrics | grep -i pass` (returns nothing).
- **Idle telnet sessions get recycled.** These routers close the exporter's
  persistent telnet session periodically (`Connection reset by peer`). The
  exporter reconnects and retries within the same scrape, so no gap is left;
  those recoveries are counted in `dsl_reconnects_total` (benign), while
  `dsl_scrape_errors_total` only counts scrapes that failed even after a retry.
- **One session at a time.** Many models allow a single telnet session; if you
  log in manually the exporter's next scrape may briefly fail and reconnect.
- **Telnet is clear-text.** A router limitation — keep this on a trusted LAN.
- **Field mapping is model-specific.** Values like SNR margin/attenuation/power
  are reported in tenths of a dB and divided by 10 here; other TP-Link models may
  label fields differently. `LOG_LEVEL=DEBUG` shows what's parsed.

## Releases

Versioned with SemVer. Pushing a `vX.Y.Z` tag triggers CI to build and publish a
multi-arch image to GHCR:

- `ghcr.io/sergiombd/tplink-dsl-exporter:vX.Y.Z` and `:X.Y` — pinned
- `:latest` — newest release
- `:edge` — latest `main` (may be unstable)

The running version is reported by `dsl_exporter_build_info{version="..."}` and
logged at startup. To cut a release, bump `__version__` in `exporter/exporter.py`
(and `version` in `exporter/pyproject.toml`), then:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

## License

MIT — see [LICENSE](LICENSE).
