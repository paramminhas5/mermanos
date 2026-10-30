"""Other Param OS lanes, read-only, no AI. Each lane becomes a small public-safe summary that rides along in state.json.

Cats Can Dance: calls the token-guarded ops_snapshot function that the CCD site already uses for /ops.
Secrets never live in this repo. Put them on your Mac in ~/.crate/lanes.env, one KEY=VALUE per line:
  CCD_SUPABASE_URL=https://jybloszaucgqlbkzquqw.supabase.co
  CCD_ANON_KEY=<the site's public anon key, from the CCD Vercel project>
  CCD_OPS_TOKEN=<the same OPS_TOKEN the CCD Vercel project uses>"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error
from pathlib import Path

def _env(cfg) -> dict:
    out = {}
    p = Path(cfg.home) / "lanes.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("="); out[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("CCD_SUPABASE_URL", "CCD_ANON_KEY", "CCD_OPS_TOKEN"):
        if os.environ.get(k): out[k] = os.environ[k]
    return out

def _fetch_ccd(env: dict, opener=urllib.request.urlopen) -> dict:
    req = urllib.request.Request(env["CCD_SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/ops_snapshot",
        data=json.dumps({"p_token": env["CCD_OPS_TOKEN"]}).encode(), method="POST",
        headers={"apikey": env["CCD_ANON_KEY"], "Authorization": "Bearer " + env["CCD_ANON_KEY"], "Content-Type": "application/json"})
    with opener(req, timeout=30) as r: return json.loads(r.read())

def summarize_ccd(raw: dict) -> dict:
    """Public-safe: counts, health and titles of events that are already public. No emails, messages or signups."""
    c = raw.get("counts", {}); runs = raw.get("runs", []); build = raw.get("build", [])
    last = {}
    for r in runs:
        last.setdefault(r["job"], r)
    failed = [dict(job=j, at=r.get("started_at"), error=(r.get("error") or "")[:120]) for j, r in last.items() if r.get("ok") is False]
    today = time.strftime("%Y-%m-%d")
    upcoming = [dict(title=e["title"], date=e.get("event_date") or e.get("date"), venue=e.get("venue"))
                for e in raw.get("ccd_events", []) if e.get("published") and (e.get("event_date") or "9999") >= today][:5]
    open_build = [dict(area=b["area"], title=b["title"], status=b["status"]) for b in build if b.get("status") in ("in_progress", "blocked")][:6]
    needs = []
    if c.get("pending"): needs.append(f"{c['pending']} scraped events waiting for you to publish or skip")
    for f in failed: needs.append(f"Job {f['job']} failed on its last run")
    for b in open_build:
        if b["status"] == "blocked": needs.append(f"Blocked: {b['title']}")
    return dict(status="ok", updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"), counts=c, upcoming=upcoming,
                jobs=[dict(job=j, ok=r.get("ok"), at=r.get("started_at")) for j, r in last.items()], failed=failed,
                build=open_build, needs_you=needs)

def collect(cfg, opener=urllib.request.urlopen) -> dict:
    lanes = {}
    env = _env(cfg)
    if not all(env.get(k) for k in ("CCD_SUPABASE_URL", "CCD_ANON_KEY", "CCD_OPS_TOKEN")):
        lanes["ccd"] = dict(status="not configured", hint="add CCD_SUPABASE_URL, CCD_ANON_KEY and CCD_OPS_TOKEN to ~/.crate/lanes.env")
    else:
        try: lanes["ccd"] = summarize_ccd(_fetch_ccd(env, opener))
        except Exception as e: lanes["ccd"] = dict(status="error", error=type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else ""))
    return lanes
