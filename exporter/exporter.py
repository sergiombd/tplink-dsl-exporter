# /// script
# requires-python = ">=3.11"
# dependencies = ["prometheus-client>=0.20"]
# ///
"""
TP-Link DSL router Prometheus exporter.

Logs into the router over telnet (password-only CLI), scrapes the DSL line and
PPPoE/WAN status blocks, and exposes them as Prometheus metrics.

The single most useful pair of signals for diagnosing "random" drops is the two
uptime counters:

  * dsl_line_uptime_seconds   -- resets when the DSL modem re-syncs (layer 1)
  * pppoe_uptime_seconds      -- resets when the PPPoE session drops (layer 2/3)

If PPPoE resets while the DSL line uptime keeps climbing, the fault is in the
PPPoE session (LCP/keepalive/idle-timeout/ISP), not the copper line. If both
reset together, the DSL line re-trained (noise, attenuation, SNR collapse).

Security: the router's `wan show connection info` output contains the PPPoE
username and password in clear text. This exporter NEVER exports or logs those
fields -- they are dropped during parsing.
"""

import logging
import os
import re
import socket
import time

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Info,
    start_http_server,
)

__version__ = "0.1.0"

# --------------------------------------------------------------------------- #
# Configuration (all via environment)
# --------------------------------------------------------------------------- #
ROUTER_HOST = os.environ.get("ROUTER_HOST", "192.168.1.1")
ROUTER_PORT = int(os.environ.get("ROUTER_TELNET_PORT", "23"))
ROUTER_PASSWORD = os.environ.get("ROUTER_PASSWORD", "admin")
ROUTER_USERNAME = os.environ.get("ROUTER_USERNAME", "")  # blank = password-only login
LISTEN_PORT = int(os.environ.get("EXPORTER_PORT", "9908"))
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "20"))
CMD_TIMEOUT = float(os.environ.get("CMD_TIMEOUT", "6"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Fields that must never leave this process.
_SECRET_KEYS = {"password", "username", "x_tp_clonedmacaddress"}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("dsl-exporter")

PROMPT = b"#"  # TP-Link(conf)#

# --------------------------------------------------------------------------- #
# Minimal telnet client (handles IAC negotiation by refusing every option)
# --------------------------------------------------------------------------- #
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


class RouterCLI:
    def __init__(self, host, port, password, username=""):
        self.host = host
        self.port = port
        self.password = password
        self.username = username
        self.sock = None

    def _strip_iac(self, data):
        out, reply, i = bytearray(), bytearray(), 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                    opt = data[i + 2]
                    if cmd == DO:
                        reply += bytes([IAC, WONT, opt])
                    elif cmd == WILL:
                        reply += bytes([IAC, DONT, opt])
                    i += 3
                    continue
                if cmd == SB:
                    j = i + 2
                    while j + 1 < len(data) and not (
                        data[j] == IAC and data[j + 1] == SE
                    ):
                        j += 1
                    i = j + 2
                    continue
                i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out), bytes(reply)

    def _read_until(self, terminators, timeout):
        """Read until any terminator (bytes) is seen or timeout elapses."""
        self.sock.settimeout(0.5)
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                if any(t in buf for t in terminators):
                    break
                continue
            if not chunk:
                break
            clean, reply = self._strip_iac(chunk)
            if reply:
                self.sock.sendall(reply)
            buf += clean
            if any(t in buf for t in terminators):
                break
        return buf.decode("ascii", "replace")

    def connect(self):
        self.close()
        log.debug("connecting to %s:%s", self.host, self.port)
        self.sock = socket.create_connection((self.host, self.port), timeout=CMD_TIMEOUT)
        banner = self._read_until([b"password:", b"login:", b"username:"], CMD_TIMEOUT)
        low = banner.lower()
        if ("login:" in low or "username:" in low) and self.username:
            self.sock.sendall(self.username.encode() + b"\r\n")
            self._read_until([b"password:"], CMD_TIMEOUT)
        # send password, wait for the CLI prompt
        self.sock.sendall(self.password.encode() + b"\r\n")
        out = self._read_until([PROMPT], CMD_TIMEOUT)
        if PROMPT.decode() not in out:
            raise RuntimeError("login failed: never reached CLI prompt")
        log.info("logged in to router CLI")

    def run(self, command):
        """Run one CLI command, return its raw text output."""
        self.sock.sendall(command.encode() + b"\r\n")
        # Commands end with a cmd:SUCC / cmd:FAIL line then the prompt.
        out = self._read_until([b"cmd:SUCC", b"cmd:FAIL", b"Command not found"], CMD_TIMEOUT)
        # drain the trailing prompt line
        self._read_until([PROMPT], 1.0)
        return out

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
_KV_RE = re.compile(r"^([A-Za-z0-9_]+)=(.*)$")


def parse_kv_block(text):
    """Parse the `key=value` lines the CLI emits inside { } blocks."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        m = _KV_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key.lower() in _SECRET_KEYS:
            continue  # never keep credentials
        result[key] = val
    return result


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Deliberately excludes "connecting"/"disconnected" so a drop reads as 0.
_TRUTHY = {"on", "1", "up", "enable", "enabled", "true", "connected"}


def onoff(value):
    return 1.0 if str(value).strip().lower() in _TRUTHY else 0.0


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
REG = CollectorRegistry()

def g(name, doc, labels=None):
    return Gauge(name, doc, labels or [], registry=REG)

# scrape health
m_up = g("dsl_up", "1 if the last router scrape succeeded, else 0")
m_scrape_duration = g("dsl_scrape_duration_seconds", "Duration of the last router scrape")
m_scrape_errors = g("dsl_scrape_errors_total", "Cumulative count of scrapes that failed even after a reconnect+retry")
m_reconnects = g("dsl_reconnects_total", "Cumulative telnet reconnects (router recycled the idle session; recovered in-cycle)")
m_build = Info("dsl_exporter_build", "Exporter build information", registry=REG)
m_build.info({"version": __version__})

# DSL line (from `adsl show info`)
m_line_status = g("dsl_line_status", "DSL line status (1=Up, 0=Down)")
m_ds_rate = g("dsl_downstream_rate_kbps", "Current downstream sync rate (kbps)")
m_us_rate = g("dsl_upstream_rate_kbps", "Current upstream sync rate (kbps)")
m_ds_max = g("dsl_downstream_max_rate_kbps", "Max attainable downstream rate (kbps)")
m_us_max = g("dsl_upstream_max_rate_kbps", "Max attainable upstream rate (kbps)")
m_ds_snr = g("dsl_downstream_snr_margin_db", "Downstream SNR margin (dB)")
m_us_snr = g("dsl_upstream_snr_margin_db", "Upstream SNR margin (dB)")
m_ds_atten = g("dsl_downstream_attenuation_db", "Downstream line attenuation (dB)")
m_us_atten = g("dsl_upstream_attenuation_db", "Upstream line attenuation (dB)")
m_ds_power = g("dsl_downstream_power_dbm", "Downstream transmit power (dBm)")
m_us_power = g("dsl_upstream_power_dbm", "Upstream transmit power (dBm)")
m_line_uptime = g("dsl_line_uptime_seconds", "DSL showtime uptime; resets on re-sync")
m_showtime_start = g("dsl_showtime_start", "Router-reported showtimeStart counter")
m_total_start = g("dsl_total_start", "Router-reported totalStart counter")
m_bitswap = g("dsl_bitswap_enabled", "Bitswap enabled (1/0)")
m_sra = g("dsl_sra_enabled", "Seamless Rate Adaptation enabled (1/0)")
m_dsl_info = Info("dsl_line", "DSL line static/config attributes", registry=REG)

# PPPoE / WAN (from `wan show connection info`)
m_ppp_status = g("pppoe_connection_status", "PPPoE connection status (1=Connected)", ["name"])
m_ppp_uptime = g("pppoe_uptime_seconds", "PPPoE session uptime; resets on drop", ["name"])
m_ppp_lasterr = g(
    "pppoe_last_connection_error_info",
    "PPPoE last connection error (label=error, value always 1)",
    ["name", "error"],
)
m_ppp_lcp_echo = g("pppoe_lcp_echo_interval_seconds", "Configured PPP LCP echo interval", ["name"])
m_ppp_lcp_retry = g("pppoe_lcp_echo_retry", "Configured PPP LCP echo retry count", ["name"])
m_ppp_idle = g("pppoe_idle_disconnect_time", "Configured idle disconnect time (0=AlwaysOn)", ["name"])
m_ppp_session = g("pppoe_session_id", "Current PPPoE session id", ["name"])
m_ppp_info = Info("pppoe_connection", "PPPoE connection attributes (no credentials)", registry=REG)

# Remember the last error label set so we can clear stale series.
_last_ppp_error_labels = {}


def _set(metric, value):
    if value is not None:
        metric.set(value)


def update_dsl(info):
    m_line_status.set(onoff(info.get("status")))
    _set(m_ds_rate, to_float(info.get("downstreamCurrRate")))
    _set(m_us_rate, to_float(info.get("upstreamCurrRate")))
    _set(m_ds_max, to_float(info.get("downstreamMaxRate")))
    _set(m_us_max, to_float(info.get("upstreamMaxRate")))
    # noise margin / attenuation / power are reported in tenths of a dB
    for metric, key in (
        (m_ds_snr, "downstreamNoiseMargin"),
        (m_us_snr, "upstreamNoiseMargin"),
        (m_ds_atten, "downstreamAttenuation"),
        (m_us_atten, "upstreamAttenuation"),
        (m_ds_power, "downstreamPower"),
        (m_us_power, "upstreamPower"),
    ):
        v = to_float(info.get(key))
        _set(metric, v / 10.0 if v is not None else None)
    _set(m_line_uptime, to_float(info.get("X_TP_UpTime")))
    _set(m_showtime_start, to_float(info.get("showtimeStart")))
    _set(m_total_start, to_float(info.get("totalStart")))
    m_bitswap.set(onoff(info.get("X_TP_Bitswap")))
    m_sra.set(onoff(info.get("X_TP_SRA")))
    m_dsl_info.info(
        {
            "modulation": info.get("modulationType", ""),
            "profile": info.get("currentProfile", "") or "auto",
            "annex": info.get("X_TP_AnnexType", ""),
            "datapath": info.get("dataPath", ""),
            "encapsulation": info.get("linkEncapsulationUsed", ""),
        }
    )


def update_pppoe(info):
    name = info.get("name", "wan")
    m_ppp_status.labels(name).set(onoff(info.get("connectionStatus")))
    _set_lbl(m_ppp_uptime, name, to_float(info.get("uptime")))
    _set_lbl(m_ppp_lcp_echo, name, to_float(info.get("PPPLCPEcho")))
    _set_lbl(m_ppp_lcp_retry, name, to_float(info.get("PPPLCPEchoRetry")))
    _set_lbl(m_ppp_idle, name, to_float(info.get("idleDisconnectTime")))
    _set_lbl(m_ppp_session, name, to_float(info.get("X_TP_SessionID")))

    error = info.get("lastConnectionError", "UNKNOWN") or "UNKNOWN"
    # clear a previous error label so only the current one reads 1
    prev = _last_ppp_error_labels.get(name)
    if prev is not None and prev != error:
        try:
            m_ppp_lasterr.remove(name, prev)
        except KeyError:
            pass
    m_ppp_lasterr.labels(name, error).set(1)
    _last_ppp_error_labels[name] = error

    m_ppp_info.info(
        {
            "name": name,
            "interface": info.get("X_TP_IfName", ""),
            "external_ip": info.get("externalIPAddress", ""),
            "remote_ip": info.get("remoteIPAddress", ""),
            "gateway": info.get("defaultGateway", ""),
            "server_mac": info.get("X_TP_ServerMACAdress", ""),
            "connection_trigger": info.get("connectionTrigger", ""),
            "auth": info.get("PPPAuthenticationProtocol", ""),
        }
    )


def _set_lbl(metric, name, value):
    if value is not None:
        metric.labels(name).set(value)


# --------------------------------------------------------------------------- #
# Scrape loop
# --------------------------------------------------------------------------- #
class Scraper:
    def __init__(self):
        self.cli = RouterCLI(ROUTER_HOST, ROUTER_PORT, ROUTER_PASSWORD, ROUTER_USERNAME)
        self.errors = 0

        self.reconnects = 0

    def _ensure_connected(self):
        if self.cli.sock is None:
            self.cli.connect()

    def _collect(self):
        """One connect+query+parse+update pass. Raises on any failure."""
        self._ensure_connected()
        adsl_raw = self.cli.run("adsl show info")
        wan_raw = self.cli.run("wan show connection info")

        adsl = parse_kv_block(adsl_raw)
        wan = parse_kv_block(wan_raw)
        if not adsl and not wan:
            raise RuntimeError("empty parse")

        if adsl:
            update_dsl(adsl)
        if wan:
            update_pppoe(wan)
        return adsl, wan

    def scrape_once(self):
        start = time.monotonic()
        try:
            try:
                adsl, wan = self._collect()
            except (OSError, EOFError, RuntimeError) as first:
                # This router recycles idle telnet sessions (ECONNRESET). Rather
                # than drop a whole scrape interval, reconnect and retry once in
                # the same cycle so we don't leave a gap that could hide a real
                # drop event.
                self.reconnects += 1
                m_reconnects.set(self.reconnects)
                log.info("stale session (%s); reconnecting and retrying", first)
                self.cli.close()
                adsl, wan = self._collect()

            m_up.set(1)
            log.debug(
                "scrape ok: line=%s ds=%s/%s kbps snr=%s ppp=%s uptime=%ss",
                adsl.get("status"),
                adsl.get("downstreamCurrRate"),
                adsl.get("downstreamMaxRate"),
                adsl.get("downstreamNoiseMargin"),
                wan.get("connectionStatus"),
                wan.get("uptime"),
            )
        except Exception as exc:  # noqa: BLE001 - want to keep the loop alive
            self.errors += 1
            m_up.set(0)
            m_scrape_errors.set(self.errors)
            log.warning("scrape failed after retry: %s", exc)
            self.cli.close()  # force fresh login next time
        finally:
            m_scrape_duration.set(time.monotonic() - start)

    def run_forever(self):
        while True:
            self.scrape_once()
            time.sleep(SCRAPE_INTERVAL)


def main():
    log.info(
        "starting DSL exporter v%s: router=%s:%s listen=:%s interval=%ss",
        __version__,
        ROUTER_HOST,
        ROUTER_PORT,
        LISTEN_PORT,
        SCRAPE_INTERVAL,
    )
    start_http_server(LISTEN_PORT, registry=REG)
    Scraper().run_forever()


if __name__ == "__main__":
    main()
