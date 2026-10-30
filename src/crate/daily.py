"""The daily brief: one deterministic pass (no AI) that produces state.json (for Param OS) and a self-contained dashboard.html."""
from __future__ import annotations
import html, json, statistics, time, urllib.parse
from collections import Counter
from pathlib import Path
from . import ableton, lanes as _lanes

DEFAULT_GOALS = [
    {"horizon": "30 days", "goal": "Finish 4 tracks", "measure": "tracks finished", "target": 4, "done": 0, "status": "in progress"},
    {"horizon": "30 days", "goal": "30 posts live", "measure": "posts", "target": 30, "done": 0, "status": "not started"},
    {"horizon": "90 days", "goal": "First EP, 4 to 5 tracks", "measure": "EP mastered", "target": 1, "done": 0, "status": "not started"},
    {"horizon": "90 days", "goal": "One live AV set on video", "measure": "set recorded", "target": 1, "done": 0, "status": "not started"},
    {"horizon": "6 months", "goal": "EP released on your own imprint", "measure": "release live", "target": 1, "done": 0, "status": "not started"},
    {"horizon": "6 months", "goal": "First bookings outside Bengaluru", "measure": "out of town gigs", "target": 2, "done": 0, "status": "not started"},
    {"horizon": "12 months", "goal": "Merman page past 100k", "measure": "followers", "target": 100000, "done": 25000, "status": "not started"},
    {"horizon": "12 months", "goal": "Monthly night or residency", "measure": "nights run", "target": 12, "done": 0, "status": "not started"},
    {"horizon": "3 years", "goal": "Top ten act in India for the genre", "measure": "rank", "target": 10, "done": 0, "status": "not started"},
    {"horizon": "5 years", "goal": "A label with other artists on it", "measure": "artists signed", "target": 3, "done": 0, "status": "not started"},
]

def goals(cfg, sets: list[dict] | None = None) -> list[dict]:
    p = cfg.home / "goals.json"
    if not p.exists(): p.write_text(json.dumps(DEFAULT_GOALS, indent=1))
    g = json.loads(p.read_text())
    if sets is not None:   # tracks finished counts itself: a project touched in the last 30 days that has a bounce next to it
        done = sum(1 for x in sets if x.get("bounces", 0) > 0 and x.get("days_ago", 999) <= 30)
        for x in g:
            if x.get("measure") == "tracks finished":
                x["done"] = done; x["auto"] = True
                x["status"] = "done" if done >= x["target"] else ("in progress" if done else x["status"])
    return g

def needs_you(sets: list[dict], fnd: list[dict]) -> list[str]:
    out = []
    if sets and sets[0]["days_ago"] >= 7: out.append(f"No Ableton session for {sets[0]['days_ago']} days. Open the newest set and finish an 8 bar loop.")
    elif not sets: out.append("No Ableton sets found. Check ableton_dirs in ~/.crate/config.toml.")
    if len(fnd) >= 10: out.append(f"{len(fnd)} finds are waiting. Press Want or Skip on a few, it teaches the next dig.")
    return out

def library(con, cfg) -> list[dict]:
    root = str(cfg.library_root.resolve()) + "/"
    b: dict[str, list[int]] = {}
    for r in con.execute("SELECT path, lossless FROM tracks WHERE path LIKE ?", (root + "%",)):
        top = r["path"][len(root):].split("/", 1)[0]
        c = b.setdefault(top, [0, 0]); c[0] += 1; c[1] += 0 if r["lossless"] else 1
    return [dict(folder=k, files=v[0], lossy=v[1]) for k, v in sorted(b.items(), key=lambda kv: -kv[1][0])]

def finds(con, n=60) -> list[dict]:
    out = []
    cutoff = int(time.strftime('%Y')) - 3
    for c in con.execute("SELECT * FROM candidates WHERE status='new' ORDER BY score DESC LIMIT ?", (n,)):
        why = json.loads(c["why"] or "[]")
        q = urllib.parse.quote(f'{c["artist"]} {c["release"] or ""}'.strip())
        out.append(dict(recent=str(c["release_year"] or "")[:4].isdigit() and int(str(c["release_year"])[:4]) >= cutoff, id=c["id"], artist=c["artist"], release=c["release"], year=c["release_year"], label=c["label"],
                        why=why[0] if why else "", links=dict(bandcamp="https://bandcamp.com/search?q=" + q,
                        discogs="https://www.discogs.com/search/?q=" + q, beatport="https://www.beatport.com/search?q=" + q)))
    return out

def _mix(fnd, n=5):
    """Today's listening: new releases first (up to 3), then deep cuts, so the list is never all 1990s."""
    new = [f for f in fnd if f["recent"]][:3]; rest = [f for f in fnd if f not in new]
    return (new + rest)[:n]

def prompts(sets: list[dict], fnd: list[dict]) -> list[dict]:
    """Things to post about, built from facts. The take is yours; these only point at what is interesting."""
    out = []
    labels = Counter(f["label"] for f in fnd[:8] if f["label"])
    if labels:
        lab, n = labels.most_common(1)[0]
        if n >= 2: out.append(dict(topic=lab, prompt=f"{n} of today's finds are on {lab}. What do they share, and which one would you play out?"))
    if len(sets) >= 3:
        recent, older = sets[0], [s["bpm"] for s in sets[1:6] if s["bpm"]]
        if recent["bpm"] and older and abs(recent["bpm"] - statistics.median(older)) >= 10:
            out.append(dict(topic=f"{recent['project']} at {recent['bpm']:g} bpm", prompt=f"Your newest set is at {recent['bpm']:g} bpm, your recent ones sit around {statistics.median(older):g}. What made you move?"))
    if sets:
        s = max(sets[:5], key=lambda x: x["clips"])
        out.append(dict(topic=s["project"], prompt=f"{s['project']} has {s['tracks']} tracks and {s['clips']} clips. Play 15 seconds of the part you are proudest of and say why."))
    if fnd: out.append(dict(topic=fnd[0]["artist"], prompt=f"Top find today is {fnd[0]['artist']}" + (f", {fnd[0]['release']}" if fnd[0]["release"] else "") + ". One thing about it that you would steal."))
    return out[:4]

def build(cfg, con) -> dict:
    sets = ableton.latest_per_project(cfg.ableton_dirs or [])
    fnd = finds(con)
    month_ago = time.time() - 30 * 86400
    g = goals(cfg, sets)
    touched = sum(1 for s in sets if s["mtime"] >= month_ago)
    return dict(schema=1, lane="merman", generated=time.strftime("%Y-%m-%dT%H:%M:%S%z"), date=time.strftime("%Y-%m-%d"),
                headline=dict(sets_touched_30d=touched, finds_waiting=len(fnd), lossy_files=sum(l["lossy"] for l in library(con, cfg)),
                              latest_project=sets[0]["project"] if sets else None, latest_bpm=sets[0]["bpm"] if sets else None,
                              days_since_last_session=sets[0]["days_ago"] if sets else None),
                today=dict(needs_you=needs_you(sets, fnd), listen=_mix(fnd), talk=prompts(sets, fnd), check_out=[dict(label=l, finds=n) for l, n in Counter(f["label"] for f in fnd if f["label"]).most_common(4)],
                           working_on=sets[:3]),
                studio=sets, discovery=fnd, library=library(con, cfg), goals=g, lanes=_lanes.collect(cfg))

def public_copy(state: dict) -> dict:
    """What is safe to host online: no file paths, no local folder names."""
    import copy
    p = copy.deepcopy(state)
    for sets in (p["studio"], p["today"]["working_on"]):
        for x in sets: x.pop("path", None)
    return p

def publish(cfg, state: dict, repo_dir: Path, push: bool = True) -> str:
    """Write the online copy into a git checkout (the ParamOS repo) and push it. Vercel redeploys on push."""
    import subprocess
    pub = public_copy(state)
    out = repo_dir / "mermanos"; out.mkdir(exist_ok=True)
    (out / "index.html").write_text(render(pub, actions=False))
    (out / "state.json").write_text(json.dumps(pub, indent=1))
    lanes_dir = repo_dir / "lanes"; lanes_dir.mkdir(exist_ok=True)
    for name, data in (pub.get("lanes") or {}).items():
        if data.get("status") == "ok": (lanes_dir / f"{name}.json").write_text(json.dumps(data, indent=1))
    import os
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    def run(*a):
        try: return subprocess.run(["git", "-C", str(repo_dir), *a], capture_output=True, text=True, env=env, timeout=60)
        except subprocess.TimeoutExpired: return subprocess.CompletedProcess(a, 1, "", "git timed out (login needed?)")
    run("add", "mermanos", "lanes")
    if not run("status", "--porcelain").stdout.strip(): return "online copy already up to date"
    run("commit", "-m", f"merman: daily {state['date']}")
    if not push: return "committed (not pushed)"
    r = run("push"); return "pushed" if r.returncode == 0 else "push failed: " + r.stderr.strip()[:200]

def write(cfg, state: dict) -> Path:
    cfg.home.mkdir(parents=True, exist_ok=True)
    (cfg.home / "state.json").write_text(json.dumps(state, indent=1))
    hist = cfg.home / "history"; hist.mkdir(exist_ok=True)
    (hist / f"{state['date']}.json").write_text(json.dumps(state["headline"]))
    out = cfg.home / "dashboard.html"; out.write_text(render(state)); return out

# ---------- html ----------
E = html.escape
def _tbl(head, rows):
    return "<div class=sc><table><thead><tr>" + "".join(f"<th>{E(h)}</th>" for h in head) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>"

def _find_row(f, actions=True):
    ln = " ".join(f'<a href="{E(u)}" target=_blank rel=noopener>{n}</a>' for n, u in (("Bandcamp", f["links"]["bandcamp"]), ("Discogs", f["links"]["discogs"]), ("Beatport", f["links"]["beatport"])))
    if not actions: return [E(f["artist"]), E(f"{f['release'] or ''} {('(' + str(f['year']) + ')') if f['year'] else ''}".strip()), E(f["label"] or ""), E(f["why"]), ln]
    act = f'<span class=act data-id="{f["id"]}"><button data-s=wanted>Want</button> <button data-s=skipped>Skip</button></span>'
    return [E(f["artist"]), E(f"{f['release'] or ''} {('(' + str(f['year']) + ')') if f['year'] else ''}".strip()), E(f["label"] or ""), E(f["why"]), ln, act]

def render(s: dict, actions: bool = True) -> str:
    h = s["headline"]; t = s["today"]
    take = (f"Last session: {E(str(h['latest_project']))} at {h['latest_bpm']:g} bpm, {h['days_since_last_session']} days ago. " if h["latest_project"] else "") + f"{h['finds_waiting']} finds waiting, {h['sets_touched_30d']} sets touched in 30 days."
    studio = _tbl(["Project", "Last edit", "BPM", "Tracks", "Clips", "Bounces"], [[E(x["project"]), E(x["date"]), f"{x['bpm']:g}" if x["bpm"] else "", x["tracks"], x["clips"], x["bounces"]] for x in s["studio"]])
    working = _tbl(["Project", "Last edit", "BPM"], [[E(x["project"]), E(x["date"]), f"{x['bpm']:g}" if x["bpm"] else ""] for x in t["working_on"]])
    fh = ["Artist", "Release", "Label", "Why", "Find it"] + ([""] if actions else [])
    listen = _tbl(fh, [_find_row(f, actions) for f in t["listen"]])
    talk = _tbl(["Topic", "Angle"], [[E(x["topic"]), E(x["prompt"])] for x in t["talk"]])
    chk = _tbl(["Label to browse", "Finds on it"], [[E(x["label"]), x["finds"]] for x in t["check_out"]])
    disc = _tbl(fh, [_find_row(f, actions) for f in s["discovery"]])
    lib = _tbl(["Folder", "Files", "Lossy"], [[E(x["folder"]), f"{x['files']:,}", f"{x['lossy']:,}"] for x in s["library"]])
    gl = _tbl(["Goal", "By", "Measure", "Progress", "Status"], [[E(x["goal"]), E(x["horizon"]), E(x["measure"]), f"{x['done']:,} / {x['target']:,}", E(x["status"])] for x in s["goals"]])
    tiles = "".join(f"<div class=tile><span>{E(k)}</span><b>{E(str(v))}</b></div>" for k, v in (("Sets touched, 30 days", h["sets_touched_30d"]), ("Finds waiting", h["finds_waiting"]), ("Lossy files to upgrade", f"{h['lossy_files']:,}"), ("Days since last session", h["days_since_last_session"])))
    tools = ('<span class=tools><button data-run=0>Refresh now</button> <button data-run=1>Dig for new music</button> <span class=mut id=runmsg></span></span>' if actions else '<a href="/paramos">Param OS</a>')
    return TEMPLATE.format(take=take, date=E(s["date"]), tiles=tiles, working=working, listen=listen, talk=talk, chk=chk, studio=studio, disc=disc, lib=lib, gl=gl, tools=tools)

TEMPLATE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Merman OS</title>
<style>:root{{--bg:#f7f6f2;--fg:#15151a;--mut:#6b6b73;--pan:#fff;--line:#e2e0d8;--acc:#2a3cff}}
@media(prefers-color-scheme:dark){{:root{{--bg:#101014;--fg:#ececf1;--mut:#9a9aa5;--pan:#18181d;--line:#2a2a31;--acc:#8d98ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:20px 16px 60px;display:flex;flex-direction:column;gap:16px}}
h1{{font:400 30px Georgia,serif;margin:0}}h2{{font-size:15px;margin:0}}.mut,.tile span{{color:var(--mut);font-size:12px}}
nav{{display:flex;gap:6px;flex-wrap:wrap}}nav button,.act button{{font:inherit;padding:5px 12px;border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:6px;cursor:pointer}}nav button.on{{background:var(--pan);font-weight:600}}
.card,.tile{{background:var(--pan);border:1px solid var(--line);border-radius:8px;padding:14px;min-width:0}}.card{{display:flex;flex-direction:column;gap:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,24rem),1fr));gap:12px}}.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:12px}}.tile b{{display:block;font:400 26px Georgia,serif}}
.sc{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th{{text-align:left;color:var(--mut);font-size:12px;font-weight:600;padding:5px 10px 5px 0;border-bottom:1px solid var(--line)}}td{{padding:7px 10px 7px 0;border-bottom:1px solid var(--line);vertical-align:top}}a{{color:var(--acc)}}
.tools button{{font:inherit;padding:5px 12px;border:1px solid var(--line);background:var(--pan);color:var(--fg);border-radius:6px;cursor:pointer}}section[hidden]{{display:none}}.act button:hover{{background:var(--line)}}.done{{opacity:.35}}</style>
<main><header><h1>Merman OS</h1><p>{take}</p>{tools}<br><span class=mut>Built {date}. No AI in this page: it reads your Ableton files, your library and your discovery list.</span></header>
<nav><button class=on data-t=today>Today</button><button data-t=studio>Studio</button><button data-t=disc>Discovery</button><button data-t=lib>Library</button><button data-t=goals>Goals</button></nav>
<section id=today class=grid><div class=card style="grid-column:1/-1"><div class=tiles>{tiles}</div></div><div class=card><h2>Listen to</h2>{listen}</div><div class=card><h2>Talk about</h2><span class=mut>Points at what is interesting. The take is yours.</span>{talk}</div><div class=card><h2>Check out</h2>{chk}</div><div class=card><h2>Working on</h2>{working}</div></section>
<section id=studio hidden><div class=card><h2>Ableton sets</h2><span class=mut>One row per project, newest first, read from the .als files.</span>{studio}</div></section>
<section id=disc hidden><div class=card><h2>New and obscure finds</h2>{disc}</div></section>
<section id=lib hidden><div class=card><h2>Library</h2>{lib}</div></section>
<section id=goals hidden><div class=card><h2>Road to top ten in India</h2><span class=mut>Edit goals.json in your crate folder to update progress.</span>{gl}</div></section></main>
<script>document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));document.querySelectorAll('section').forEach(s=>s.hidden=s.id!==b.dataset.t)}});
document.querySelectorAll('.act button').forEach(b=>b.onclick=async()=>{{const id=b.parentNode.dataset.id;try{{const r=await fetch('/api/mark',{{method:'POST',body:JSON.stringify({{id:+id,status:b.dataset.s}})}});if(!r.ok)throw 0;document.querySelectorAll('.act[data-id="'+id+'"]').forEach(a=>a.closest('tr').classList.add('done'))}}catch(e){{b.title='Run: crate '+(b.dataset.s=='wanted'?'want':'skip')+' '+id;b.textContent=b.textContent+' (run crate serve to click)'}}}});document.querySelectorAll('[data-run]').forEach(b=>b.onclick=async()=>{{const m=document.getElementById('runmsg');document.querySelectorAll('[data-run]').forEach(x=>x.disabled=true);m.textContent=b.dataset.run=='1'?'Digging, this can take a few minutes. You can leave this page open.':'Refreshing...';try{{await fetch('/api/run',{{method:'POST',body:JSON.stringify({{discover:b.dataset.run=='1'}})}});const t=setInterval(async()=>{{try{{const s=await (await fetch('/api/status')).json();if(!s.on){{clearInterval(t);if(s.ok===false){{m.textContent='Did not finish. See ~/.crate/daily.log';document.querySelectorAll('[data-run]').forEach(x=>x.disabled=false)}}else location.reload()}}}}catch(e){{}}}},3000)}}catch(e){{m.textContent='Could not start';document.querySelectorAll('[data-run]').forEach(x=>x.disabled=false)}}}});</script>"""
