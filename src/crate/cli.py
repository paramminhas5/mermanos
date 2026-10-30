from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
from . import config as C, db, scan as S, organize as O, acquire as Q, taste as T, voice as V, posts as P

def _ctx():
    home = C.home_dir()
    if not (home / "config.toml").exists(): sys.exit("Run `crate init` first.")
    cfg = C.load(home); return cfg, db.connect(cfg.db_path)

def _clients(cfg, con):
    from .sources.http import Http
    from .sources.musicbrainz import MusicBrainz
    from .sources.popularity import ListenBrainz, LastFm, Discogs
    h = Http(con, f"crate/0.1 ({cfg.contact})")
    return MusicBrainz(h), ListenBrainz(h, cfg.lb_token), (LastFm(h, cfg.lastfm_key) if cfg.lastfm_key else None), (Discogs(h, cfg.discogs_token) if cfg.discogs_token else None)

def cmd_init(a):
    home = C.init_home(); print(f"Created {home}\nEdit {home/'config.toml'}, then put 10+ of your own past posts in {home/'voice'}/posts.txt (separate posts with a line containing ---).")

def cmd_scan(a):
    cfg, con = _ctx()
    for root in ([Path(a.path)] if a.path else [cfg.library_root, cfg.own_music_dir]):
        if root.exists(): print(root, S.scan(con, root))
        else: print(f"skip {root} (does not exist)")
    print("candidates now owned:", Q.mark_owned(con))

def cmd_report(a):
    cfg, con = _ctx(); r = S.quality_report(con, cfg.library_root)
    print(f"{r['tracks']} tracks, {r['albums']} albums, {r['lossless_pct']}% lossless. Codecs: {r['by_codec']}")
    print(f"{len(r['albums_to_upgrade'])} albums have lossy tracks (buy or rip lossless when you can)"); [print("  ", x) for x in r["albums_to_upgrade"][:25]]
    if r["low_bitrate"]: print(f"{len(r['low_bitrate'])} low-bitrate mp3s:"); [print("  ", x) for x in r["low_bitrate"][:15]]
    if r["untagged"]: print(f"{len(r['untagged'])} files missing artist/title tags (they go to _review)")

def cmd_organize(a):
    cfg, con = _ctx()
    if a.undo is not None: O.undo(con, a.undo or None); return
    src = Path(a.src) if a.src else cfg.library_root
    S.scan(con, src)
    rows = con.execute("SELECT * FROM tracks WHERE path LIKE ?", (str(src.resolve()) + "%",)).fetchall()
    moves = O.plan(rows, cfg.library_root, src)
    rep = cfg.reports_dir / f"organize_{time.strftime('%Y%m%d_%H%M%S')}.json"; cfg.reports_dir.mkdir(exist_ok=True, parents=True)
    rep.write_text(json.dumps([m.__dict__ for m in moves], indent=1))
    print(f"{O.summarize(moves) or 'nothing to do'}. Full plan: {rep}")
    for m in moves[:12]: print(f"  [{m.kind}] {Path(m.src).name}  ->  {Path(m.dst).relative_to(cfg.library_root) if cfg.library_root in Path(m.dst).parents else m.dst}")
    if a.apply and moves: O.apply(con, moves, src)
    elif moves: print("Dry run. Re-run with --apply to move files (every move is journalled and undoable).")

def cmd_dupes(a):
    cfg, con = _ctx()
    for r in con.execute("SELECT quick_hash,COUNT(*) n FROM tracks GROUP BY quick_hash HAVING n>1"):
        print("--"); [print("  ", x["path"]) for x in con.execute("SELECT path FROM tracks WHERE quick_hash=?", (r["quick_hash"],))]

def cmd_ingest(a):
    cfg, con = _ctx(); r = Q.ingest(con, cfg, apply=a.apply); print(json.dumps(r, indent=1))
    if not a.apply and r.get("plan"): print("Dry run. Re-run with --apply.")

def cmd_taste(a):
    cfg, con = _ctx(); print(T.explain(T.build(con, cfg)))

def cmd_discover(a):
    cfg, con = _ctx()
    if a.obscurity is not None: cfg.obscurity = a.obscurity
    if getattr(a, 'since', None): cfg.since = a.since
    from .discover import discover
    mb, lb, lf, dg = _clients(cfg, con)
    print(f"Sources: MusicBrainz, ListenBrainz{', Last.fm' if lf else ''}{', Discogs' if dg else ''}. First run takes a few minutes (rate limits), reruns are cached.")
    out = discover(con, cfg, mb, lb, lf, dg); print(f"{len(out)} candidates. See them with `crate candidates`.")

def cmd_candidates(a):
    cfg, con = _ctx()
    for c in con.execute("SELECT * FROM candidates WHERE status=? ORDER BY score DESC LIMIT ?", (a.status, a.top)):
        why = json.loads(c["why"] or "[]")
        print(f'#{c["id"]:<4} {c["artist"]}' + (f' - {c["release"]} ({c["release_year"]})' if c["release"] else "") + f'  [{c["label"] or "?"}]  score {c["score"]}')
        for w in why[:3]: print("       ", w)

def _mark(a, status):
    cfg, con = _ctx()
    for i in a.ids: con.execute("UPDATE candidates SET status=? WHERE id=?", (status, i))
    con.commit(); print(f"marked {len(a.ids)} as {status}")

def cmd_wantlist(a):
    cfg, con = _ctx(); p = Q.export_wantlist(con, cfg.reports_dir / "wantlist.md", a.new); print(f"Wrote {p}")

def cmd_studio(a):
    try: from . import studio as ST
    except ModuleNotFoundError: sys.exit('Studio tools need the audio extras: pip install -e ".[audio]"')
    cfg, con = _ctx()
    if a.what == "analyze": print("analysed", ST.analyze_batch(con, cfg, a.limit), "tracks")
    elif a.what == "teardown": print(ST.teardown(Path(a.args[0])))
    elif a.what == "compare":
        if not a.refs or not a.args: sys.exit("usage: crate studio compare YOURTRACK.wav [MORE.wav] --refs REF1.flac REF2.flac")
        from . import analyze as A
        print(ST.compare([A.analyze(Path(p)) for p in a.args], [A.analyze(Path(p)) for p in a.refs]))
    elif a.what == "gaps":
        own = [json.loads(r["features"]) for r in con.execute("SELECT features FROM tracks WHERE features IS NOT NULL AND path LIKE ?", (str(cfg.own_music_dir.resolve()) + "%",))]
        lib = [json.loads(r["features"]) for r in con.execute("SELECT features FROM tracks WHERE features IS NOT NULL AND path NOT LIKE ?", (str(cfg.own_music_dir.resolve()) + "%",))]
        for n, o, l, z in ST.gaps(own, lib): print(f"{n:<18} yours {o:7.1f}  collection {l:7.1f}  z {z:+.2f}")
    elif a.what == "lesson":
        t = ST.lesson(con, cfg); (cfg.reports_dir / f"lesson_{time.strftime('%Y%m%d')}.md").write_text(t); print(t)
    elif a.what == "note": ST.note_add(con, a.args[0], a.args[1], a.args[2] if len(a.args) > 2 else None); print("saved")
    elif a.what == "notes": print(ST.notes_markdown(con))

def cmd_voice(a):
    cfg, con = _ctx()
    if a.what == "import":
        for p in V.split_posts(Path(a.arg).read_text()): con.execute("INSERT INTO voice(text,weight,source,created) VALUES(?,?,?,?)", (p, 1.0, "seed", time.time()))
        con.commit(); print("imported")
    else:
        p = V.profile(V.load_samples(cfg, con)); print(json.dumps(p, indent=1))
        if p.get("n", 0) < 10: print("\nOnly", p.get("n", 0), "posts. Give it 15+ of your real posts for a reliable profile.")

def cmd_post(a):
    cfg, con = _ctx()
    if a.what == "new": print(f"created {P._path(cfg, P.new(con, cfg, int(a.arg)))}. Write your TAKE in it, then `crate post finalize <id>`.")
    elif a.what == "finalize":
        t, i = P.finalize(con, cfg, int(a.arg)); print(t); print("\n".join(i) or "lint clean")
    elif a.what == "approve": print("approved;", *(P.approve(con, cfg, int(a.arg), a.force) or ["lint clean"]), sep="\n")
    elif a.what == "export":
        for i, t in P.approved(con): print(f"--- post {i} ---\n{t}\n")
    else:
        for r in con.execute("SELECT id,status,candidate_id FROM posts ORDER BY id"): print(r["id"], r["status"], "candidate", r["candidate_id"])

def cmd_weekly(a):
    cfg, con = _ctx(); today = time.strftime("%Y-%m-%d"); out = [f"# Weekly crate report {today}", ""]
    for root in (cfg.library_root, cfg.own_music_dir):
        if root.exists(): S.scan(con, root, log=lambda *_: None)
    r = Q.ingest(con, cfg, apply=a.apply, log=lambda *_: None)
    out += ["## Inbox", f"{r.get('inbox_files', 0)} files. Plan: {r.get('plan')}. Applied: {r.get('applied')}.", ""]
    if r.get("failed_verify"): out += ["Failed verification (not filed):"] + [f"- {p}: {w}" for p, w in r["failed_verify"]] + [""]
    from .discover import discover
    mb, lb, lf, dg = _clients(cfg, con)
    try: cands = discover(con, cfg, mb, lb, lf, dg, log=lambda *_: None)
    except Exception as e: cands = []; out += [f"Discovery failed: {e}", ""]
    out += ["## New finds, most obscure and closest to your taste first"]
    for c in con.execute("SELECT * FROM candidates WHERE status='new' ORDER BY score DESC LIMIT 15"):
        out.append(f'- #{c["id"]} **{c["artist"]}**' + (f' - {c["release"]} ({c["release_year"]})' if c["release"] else "") + f' [{c["label"] or "?"}]: ' + "; ".join(json.loads(c["why"])[:2]))
    Q.export_wantlist(con, cfg.reports_dir / "wantlist.md")
    try:
        from . import studio as ST
        n = ST.analyze_batch(con, cfg, 12, log=lambda *_: None); out += ["", f"## Studio", f"Analysed {n} tracks."]
        out.append(ST.lesson(con, cfg).split("\n")[0])
    except ModuleNotFoundError: out += ["", "## Studio", "Skipped (install the audio extras to enable)."]
    for c in con.execute("SELECT id FROM candidates WHERE status='owned' AND id NOT IN (SELECT candidate_id FROM posts)"):
        out.append(f"- Owned now, post scaffold created: {P._path(cfg, P.new(con, cfg, c['id']))}")
    rp = cfg.reports_dir / f"weekly_{today}.md"; rp.parent.mkdir(exist_ok=True, parents=True); rp.write_text("\n".join(out)); print("\n".join(out)); print(f"\nSaved {rp}")

def cmd_daily(a):
    """Everything for today, no AI: Ableton sets, library counts, discovery (refreshed weekly), dashboard + state.json."""
    from . import daily
    cfg, con = _ctx()
    if a.scan and cfg.library_root.exists(): S.scan(con, cfg.library_root); Q.mark_owned(con)
    stamp = cfg.home / "last_discovery"
    stale = (not stamp.exists()) or (time.time() - stamp.stat().st_mtime > a.every * 86400)
    if a.discover or (stale and not a.skip_discover):
        try:
            from .discover import discover
            mb, lb, lf, dg = _clients(cfg, con); discover(con, cfg, mb, lb, lf, dg); stamp.touch()
        except Exception as e: print("discovery skipped:", e)
    st = daily.build(cfg, con); out = daily.write(cfg, st); print("wrote", out, "and", cfg.home / "state.json")
    if cfg.publish_dir and not a.no_publish: print("online:", daily.publish(cfg, st, cfg.publish_dir))

def cmd_serve(a):
    """Local dashboard with working Want/Skip buttons. Rebuilds the page from disk on each load; never calls the network."""
    import http.server, socketserver, subprocess, sys, webbrowser
    from . import daily
    cfg, con0 = _ctx(); con0.close()
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *x): pass
        def do_GET(self):
            c = db.connect(cfg.db_path)
            try: body = daily.render(daily.build(cfg, c)).encode()
            finally: c.close()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
            if self.path == "/api/run":
                cmd = [sys.executable, "-m", "crate.cli", "daily"] + (["--discover"] if d.get("discover") else [])
                r = subprocess.run(cmd, capture_output=True, text=True)
                self.send_response(200 if r.returncode == 0 else 500); self.end_headers(); return
            if d.get("status") in ("wanted", "skipped") and isinstance(d.get("id"), int):
                c = db.connect(cfg.db_path); c.execute("UPDATE candidates SET status=? WHERE id=?", (d["status"], d["id"])); c.commit(); c.close()
                self.send_response(200)
            else: self.send_response(400)
            self.end_headers()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", a.port), H) as srv:
        url = f"http://127.0.0.1:{a.port}/"; print("Merman OS at", url, "(Ctrl-C to stop)")
        if not a.no_open: webbrowser.open(url)
        try: srv.serve_forever()
        except KeyboardInterrupt: pass

def cmd_schedule(a):
    """Run `crate daily` every morning. macOS: writes a launchd agent. Elsewhere: prints a cron line."""
    import shutil, sys
    exe = shutil.which("crate") or f"{sys.executable} -m crate.cli"; h, m = a.at.split(":")
    if sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents/com.merman.crate.plist"
        args = "".join(f"<string>{x}</string>" for x in exe.split() + ["daily"])
        body = f"""<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>com.merman.crate</string><key>ProgramArguments</key><array>{args}</array><key>StartCalendarInterval</key><dict><key>Hour</key><integer>{int(h)}</integer><key>Minute</key><integer>{int(m)}</integer></dict><key>StandardOutPath</key><string>{C.home_dir()}/daily.log</string><key>StandardErrorPath</key><string>{C.home_dir()}/daily.log</string></dict></plist>"""
        if a.install: plist.write_text(body); print("wrote", plist, "\nNow run: launchctl load", plist)
        else: print(body, "\nRe-run with --install to write it to", plist)
    else: print(f"{int(m)} {int(h)} * * * {exe} daily >> {C.home_dir()}/daily.log 2>&1")

def main(argv=None):
    p = argparse.ArgumentParser(prog="mermanos", description="Personal crate-digging agent"); sp = p.add_subparsers(dest="cmd", required=True)
    def add(name, fn, **kw):
        s = sp.add_parser(name); s.set_defaults(fn=fn)
        for k, v in kw.items(): s.add_argument(k, **v)
        return s
    add("init", cmd_init)
    add("scan", cmd_scan, path=dict(nargs="?"))
    add("report", cmd_report)
    o = add("organize", cmd_organize); o.add_argument("--apply", action="store_true"); o.add_argument("--src"); o.add_argument("--undo", nargs="?", const="")
    add("dupes", cmd_dupes)
    i = add("ingest", cmd_ingest); i.add_argument("--apply", action="store_true")
    add("taste", cmd_taste)
    d = add("discover", cmd_discover); d.add_argument("--obscurity", type=float); d.add_argument("--since", type=int, help="only surface releases from this year on")
    c = add("candidates", cmd_candidates); c.add_argument("--status", default="new"); c.add_argument("--top", type=int, default=20)
    w = add("want", lambda a: _mark(a, "wanted")); w.add_argument("ids", nargs="+", type=int)
    k = add("skip", lambda a: _mark(a, "skipped")); k.add_argument("ids", nargs="+", type=int)
    wl = add("wantlist", cmd_wantlist); wl.add_argument("--new", type=int, default=0)
    s = add("studio", cmd_studio); s.add_argument("what", choices=["analyze", "teardown", "compare", "gaps", "lesson", "note", "notes"]); s.add_argument("args", nargs="*"); s.add_argument("--limit", type=int, default=20); s.add_argument("--refs", nargs="+")
    v = add("voice", cmd_voice); v.add_argument("what", choices=["show", "import"]); v.add_argument("arg", nargs="?")
    po = add("post", cmd_post); po.add_argument("what", choices=["new", "finalize", "approve", "export", "list"]); po.add_argument("arg", nargs="?"); po.add_argument("--force", action="store_true")
    dl = add("daily", cmd_daily); dl.add_argument("--scan", action="store_true", help="rescan the library too"); dl.add_argument("--discover", action="store_true"); dl.add_argument("--skip-discover", action="store_true"); dl.add_argument("--no-publish", action="store_true"); dl.add_argument("--every", type=float, default=7, help="days between discovery refreshes")
    sv = add("serve", cmd_serve); sv.add_argument("--port", type=int, default=8765); sv.add_argument("--no-open", action="store_true")
    sc = add("schedule", cmd_schedule); sc.add_argument("--at", default="08:00"); sc.add_argument("--install", action="store_true")
    wk = add("weekly", cmd_weekly); wk.add_argument("--apply", action="store_true")
    a = p.parse_args(argv); a.fn(a)

if __name__ == "__main__": main()
