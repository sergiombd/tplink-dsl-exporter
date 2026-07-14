# /// script
# requires-python = ">=3.11"
# ///
"""
VDSL test dead-man's switch (LAN-only; needs NO internet).

Polls the Archer VR300 over telnet and guarantees internet comes back:
  * SUCCESS  -> PPPoE reconnects (connectionStatus=Connected + external IP) within
               the proving window after the line change is detected. Leaves config as-is.
  * TIMEOUT  -> revert DSL modulation to REVERT_MODE via headless webui (set-mode.js),
               then confirm PPPoE reconnects. Retries; last resort `dev reboot`.

Everything is timestamped to LOG_FILE so the blackout is fully reconstructable.

Env:
  ROUTER_HOST, ROUTER_TELNET_PORT, ROUTER_PASSWORD, ROUTER_USERNAME
  PROVE_SEC (default 300)   proving window after change detected
  HARDCAP_SEC (default 480) absolute cap from arm
  POLL_SEC (default 10)
  REVERT_MODE (default "Auto Sync-up")
  BASELINE_MOD (default "ADSL_2plus")
  LOG_FILE (default ./watchdog.log)
  SETMODE_DIR (dir containing set-mode.js; default script dir)
  FORCE_REVERT=1  -> skip waiting, immediately perform revert+confirm (rehearsal)
"""
import os, socket, time, subprocess, sys, datetime

HOST=os.environ.get("ROUTER_HOST","192.168.1.1"); PORT=int(os.environ.get("ROUTER_TELNET_PORT","23"))
PW=os.environ["ROUTER_PASSWORD"]; USER=os.environ.get("ROUTER_USERNAME","")
PROVE=int(os.environ.get("PROVE_SEC","300")); HARDCAP=int(os.environ.get("HARDCAP_SEC","480"))
POLL=int(os.environ.get("POLL_SEC","10")); REVERT_MODE=os.environ.get("REVERT_MODE","Auto Sync-up")
BASELINE=os.environ.get("BASELINE_MOD","ADSL_2plus")
HERE=os.path.dirname(os.path.abspath(__file__))
SETMODE_DIR=os.environ.get("SETMODE_DIR",HERE)
LOG_FILE=os.environ.get("LOG_FILE",os.path.join(HERE,"watchdog.log"))
FORCE_REVERT=os.environ.get("FORCE_REVERT")=="1"

IAC,DONT,DO,WONT,WILL,SB,SE=255,254,253,252,251,250,240; PROMPT=b"#"
def _strip(data):
    out,reply,i=bytearray(),bytearray(),0
    while i<len(data):
        b=data[i]
        if b==IAC and i+1<len(data):
            c=data[i+1]
            if c in (DO,DONT,WILL,WONT) and i+2<len(data):
                o=data[i+2]
                if c==DO: reply+=bytes([IAC,WONT,o])
                elif c==WILL: reply+=bytes([IAC,DONT,o])
                i+=3; continue
            if c==SB:
                j=i+2
                while j+1<len(data) and not(data[j]==IAC and data[j+1]==SE): j+=1
                i=j+2; continue
            i+=2; continue
        out.append(b); i+=1
    return bytes(out),bytes(reply)

class CLI:
    def __init__(s): s.s=None
    def ru(s,terms,to):
        s.s.settimeout(0.5); buf=bytearray(); dl=time.monotonic()+to
        while time.monotonic()<dl:
            try: ch=s.s.recv(4096)
            except socket.timeout:
                if any(t in buf for t in terms): break
                continue
            if not ch: break
            cl,rp=_strip(ch)
            if rp: s.s.sendall(rp)
            buf+=cl
            if any(t in buf for t in terms): break
        return buf.decode("ascii","replace")
    def conn(s):
        s.close(); s.s=socket.create_connection((HOST,PORT),timeout=6)
        b=s.ru([b"password:",b"login:",b"username:"],6).lower()
        if ("login:" in b or "username:" in b) and USER:
            s.s.sendall(USER.encode()+b"\r\n"); s.ru([b"password:"],6)
        s.s.sendall(PW.encode()+b"\r\n")
        if "#" not in s.ru([PROMPT],6): raise RuntimeError("login failed")
    def run(s,cmd,to=4.0):
        s.s.sendall(cmd.encode()+b"\r\n")
        out=s.ru([b"cmd:SUCC",b"cmd:FAIL",b"Command not found"],to); s.ru([PROMPT],1.0); return out
    def close(s):
        if s.s:
            try: s.s.close()
            except OSError: pass
            s.s=None

def kv(text):
    d={}
    for ln in text.splitlines():
        ln=ln.strip()
        if "=" in ln and not ln.startswith("#"):
            k,_,v=ln.partition("="); d[k.strip()]=v.strip()
    return d

def now(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_logf=open(LOG_FILE,"a",buffering=1)
def log(msg):
    line=f"{now()} {msg}"; print(line,flush=True); _logf.write(line+"\n")

def sample(cli):
    for attempt in (1,2):
        try:
            if cli.s is None: cli.conn()
            a=kv(cli.run("adsl show info")); w=kv(cli.run("wan show connection info"))
            return {
                "mod":a.get("modulationType",""), "line":a.get("status",""),
                "ds":a.get("downstreamCurrRate",""), "us":a.get("upstreamCurrRate",""),
                "snr":a.get("downstreamNoiseMargin",""), "lineup":a.get("X_TP_UpTime",""),
                "ppp":w.get("connectionStatus",""), "extip":w.get("externalIPAddress",""),
                "pppup":w.get("uptime",""), "err":w.get("lastConnectionError",""),
            }
        except Exception as e:
            cli.close()
            if attempt==2: return {"error":str(e)}
    return {"error":"unreachable"}

def fmt(s):
    if "error" in s: return f"POLL error={s['error']}"
    return (f"mod={s['mod']:<10} line={s['line']:<5} ds={s['ds']:>6} snr={s['snr']:>4} "
            f"ppp={s['ppp']:<12} extip={s['extip']:<15} lineup={s['lineup']} err={s['err']}")

def internet_up(s):
    return ("error" not in s and s.get("ppp","").lower()=="connected"
            and s.get("extip","") not in ("","0.0.0.0"))

def do_revert(cli):
    log(f"REVERT: setting DSL modulation -> '{REVERT_MODE}' via headless webui")
    env=dict(os.environ); env["MODE"]=REVERT_MODE; env.pop("DRY_RUN",None)
    for attempt in range(1,4):
        try:
            r=subprocess.run(["node","set-mode.js"],cwd=SETMODE_DIR,env=env,
                             capture_output=True,text=True,timeout=90)
            log(f"revert attempt {attempt} rc={r.returncode} out={r.stdout.strip()[-300:]} err={r.stderr.strip()[-200:]}")
            if r.returncode==0: return True
        except Exception as e:
            log(f"revert attempt {attempt} EXC {e}")
        time.sleep(5)
    log("REVERT via webui FAILED 3x -> last resort: dev reboot")
    try:
        if cli.s is None: cli.conn()
        cli.run("dev reboot",to=3.0); log("issued dev reboot")
    except Exception as e:
        log(f"dev reboot EXC {e}")
    return False

def wait_internet(cli, secs, tag):
    log(f"{tag}: waiting up to {secs}s for internet to return...")
    dl=time.monotonic()+secs
    while time.monotonic()<dl:
        s=sample(cli); log(f"  {tag} {fmt(s)}")
        if internet_up(s): log(f"{tag}: INTERNET RESTORED (extip={s['extip']})"); return True
        time.sleep(POLL)
    log(f"{tag}: internet NOT restored within {secs}s"); return False

def main():
    log("="*70)
    log(f"WATCHDOG ARMED host={HOST} prove={PROVE}s hardcap={HARDCAP}s poll={POLL}s "
        f"revert_mode='{REVERT_MODE}' baseline={BASELINE} force_revert={FORCE_REVERT}")
    cli=CLI()
    base=sample(cli); log(f"baseline {fmt(base)}")

    if FORCE_REVERT:
        log("FORCE_REVERT rehearsal: performing revert + recovery confirmation now")
        do_revert(cli)
        ok=wait_internet(cli,180,"POST-REVERT")
        log(f"REHEARSAL RESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    t0=time.monotonic(); changed_at=None
    while True:
        s=sample(cli); log(fmt(s))
        el=time.monotonic()-t0
        # detect the line leaving baseline (retrain / drop / modulation change)
        if changed_at is None:
            if ("error" not in s and (s["line"].lower()!="up" or (s["mod"] and s["mod"]!=BASELINE) or not internet_up(s))):
                changed_at=time.monotonic(); log(f"CHANGE DETECTED after {el:.0f}s (mod={s['mod']} line={s['line']} ppp={s['ppp']})")
        else:
            # proving window: success if internet is back
            if internet_up(s):
                log(f"SUCCESS: internet up with mod={s['mod']} -> leaving config in place. EXIT.")
                return 0
            if time.monotonic()-changed_at>=PROVE:
                log(f"PROVING window ({PROVE}s) expired without internet -> REVERT")
                do_revert(cli); wait_internet(cli,180,"POST-REVERT"); return 0
        if el>=HARDCAP:
            if changed_at is None:
                log(f"HARDCAP {HARDCAP}s reached, no change ever detected -> nothing to do. EXIT.")
                return 0
            log(f"HARDCAP {HARDCAP}s reached -> REVERT")
            do_revert(cli); wait_internet(cli,180,"POST-REVERT"); return 0
        time.sleep(POLL)

if __name__=="__main__":
    sys.exit(main())
