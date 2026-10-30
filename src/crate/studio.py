"""'Make better music' tooling: reverse-engineer tracks you admire, compare your tracks against references, keep a notebook.
It does not judge taste. It shows where your measurements differ from the music you chose as targets."""
from __future__ import annotations
import json, statistics, time
from pathlib import Path
from . import analyze as A

HINT = {"sub 20-60": "sub weight", "bass 60-250": "bass body", "low-mid 250-500": "low-mid build-up / boxiness", "mid 500-2k": "lead and vocal presence",
        "high-mid 2-6k": "bite and clarity", "high 6-12k": "top-end sheen", "air 12-20k": "air"}

def ensure_features(con, path: str, force: bool = False) -> dict | None:
    r = con.execute("SELECT features FROM tracks WHERE path=?", (path,)).fetchone()
    if r and r["features"] and not force: return json.loads(r["features"])
    f = A.analyze(Path(path))
    if r: con.execute("UPDATE tracks SET features=? WHERE path=?", (json.dumps(f), path)); con.commit()
    return f

def analyze_batch(con, cfg, limit: int = 20, log=print) -> int:
    """Own music first, then library tracks from your highest-weight artists."""
    own = str(cfg.own_music_dir.resolve())
    rows = con.execute("SELECT path FROM tracks WHERE features IS NULL AND path LIKE ? LIMIT ?", (own + "%", limit)).fetchall()
    if len(rows) < limit:
        rows += con.execute("""SELECT path FROM tracks WHERE features IS NULL AND path NOT LIKE ? AND lossless=1
                               GROUP BY album ORDER BY COUNT(*) DESC LIMIT ?""", (own + "%", limit - len(rows))).fetchall()
    n = 0
    for r in rows:
        try: ensure_features(con, r["path"]); n += 1
        except Exception as e: log(f"  analysis failed for {r['path']}: {e}")
    return n

def teardown(path: Path, f: dict | None = None) -> str:
    f = f or A.analyze(path)
    t, k = f["tempo"], f["key"]
    L = [f"# Teardown: {path.stem}", "",
         f"- Length {int(f['duration'] // 60)}:{int(f['duration'] % 60):02d}",
         f"- Tempo {t['bpm']} BPM (confidence {t['confidence']})" if t.get("bpm") else "- Tempo: no steady pulse found",
         f"- Key {k['key']} (runner-up {k['runner_up']}). {k['note']}".rstrip(),
         f"- Loudness {f['lufs']} LUFS, sample peak {f['sample_peak_db']} dBFS, crest factor {f['crest_db']} dB",
         f"- Stereo width {f['width_db']} dB (side vs mid), low-end L/R correlation {f['low_end_correlation']}", "",
         "## Spectral balance (dB relative to total)"]
    L += [f"- {b}: {v}" for b, v in f["bands"].items()]
    if f.get("sections"):
        L += ["", "## Arrangement map (bar-aligned)", "| time | bars | feel | level dB | low dB |", "|---|---|---|---|---|"]
        for s in f["sections"]:
            m1, s1, m2, s2 = int(s["start"] // 60), s["start"] % 60, int(s["end"] // 60), s["end"] % 60
            L.append(f"| {m1}:{s1:04.1f} to {m2}:{s2:04.1f} | {s['bars']} | {s['feel']} | {s['level_db']} | {s['low_db']} |")
        L += ["", "Listen at each boundary and note what enters or leaves. That is the arrangement."]
    return "\n".join(L)

def _mean(fs: list[dict], getter) -> float:
    vals = [getter(f) for f in fs if getter(f) is not None]
    return statistics.fmean(vals) if vals else float("nan")

def compare(own: list[dict], refs: list[dict]) -> str:
    L = ["# Reference comparison", "", f"Your {len(own)} track(s) against {len(refs)} reference(s). Differences are pointers, not rules.", ""]
    rows = []
    def diff(name, g, unit, thresh):
        a, b = _mean(own, g), _mean(refs, g)
        rows.append((name, a, b, a - b, unit, thresh))
    diff("Loudness", lambda f: f["lufs"], "LUFS", 2.0)
    diff("Crest factor", lambda f: f["crest_db"], "dB", 2.0)
    diff("Stereo width", lambda f: f["width_db"], "dB", 3.0)
    diff("Low-end correlation", lambda f: f["low_end_correlation"], "", 0.05)
    for b in A.BANDS: diff(b, lambda f, b=b: f["bands"].get(b), "dB", 3.0)
    L += ["| measure | yours | refs | delta |", "|---|---|---|---|"]
    L += [f"| {n} | {a:.2f} | {r:.2f} | {d:+.2f} {u} |" for n, a, r, d, u, _ in rows]
    L += ["", "## Where to look first"]
    notes = []
    for n, a, r, d, u, th in sorted(rows, key=lambda x: -abs(x[3]) / x[5]):
        if abs(d) < th: continue
        if n in HINT_BANDS: notes.append(f"- {n}: {abs(d):.1f} dB {'heavier' if d > 0 else 'lighter'} than your references. Check {HINT[n]}.")
        elif n == "Loudness": notes.append(f"- Loudness is {abs(d):.1f} LU {'above' if d > 0 else 'below'} your references. Compare at matched volume before judging anything else.")
        elif n == "Crest factor": notes.append(f"- Crest factor is {abs(d):.1f} dB {'higher' if d > 0 else 'lower'}: your tracks are {'punchier and more dynamic' if d > 0 else 'more compressed'} than the references.")
        elif n == "Stereo width": notes.append(f"- Stereo image is {'wider' if d > 0 else 'narrower'} than the references by {abs(d):.1f} dB.")
        elif n == "Low-end correlation" and a < 0.9: notes.append(f"- Low end is not mono-safe (L/R correlation {a:.2f} below 120 Hz). Worth checking on a club system or in mono.")
    L += notes or ["- Nothing differs by more than the thresholds. Your measurements sit inside your references."]
    return "\n".join(L)

HINT_BANDS = set(A.BANDS)

def gaps(own: list[dict], lib: list[dict]) -> list[tuple[str, float, float, float]]:
    """(measure, own mean, library mean, z-score) sorted by how far your music sits from your own collection."""
    out = []
    getters = {"loudness LUFS": lambda f: f["lufs"], "crest dB": lambda f: f["crest_db"], "stereo width dB": lambda f: f["width_db"]}
    getters.update({b: (lambda f, b=b: f["bands"].get(b)) for b in A.BANDS})
    for name, g in getters.items():
        lv = [g(f) for f in lib if g(f) is not None]; ov = [g(f) for f in own if g(f) is not None]
        if len(lv) < 5 or not ov: continue
        sd = statistics.pstdev(lv) or 1.0
        out.append((name, statistics.fmean(ov), statistics.fmean(lv), (statistics.fmean(ov) - statistics.fmean(lv)) / sd))
    return sorted(out, key=lambda x: -abs(x[3]))

def lesson(con, cfg) -> str:
    own_p = str(cfg.own_music_dir.resolve())
    def feats(where, params=()):
        return [(r["path"], json.loads(r["features"])) for r in con.execute(f"SELECT path,features FROM tracks WHERE features IS NOT NULL AND {where}", params)]
    own, lib = feats("path LIKE ?", (own_p + "%",)), feats("path NOT LIKE ?", (own_p + "%",))
    if len(lib) < 5: return "Not enough analysed tracks yet. Run `crate studio analyze --limit 40` first."
    if not own: return "No analysed tracks of yours yet. Put bounces in your own_music_dir, `crate scan`, then `crate studio analyze`."
    g = gaps([f for _, f in own], [f for _, f in lib])
    name, a, l, z = g[0]
    getter = (lambda f: f["lufs"]) if name.startswith("loud") else (lambda f: f["crest_db"]) if name.startswith("crest") else (lambda f: f["width_db"]) if name.startswith("stereo") else (lambda f: f["bands"].get(name))
    pool = [(p, getter(f)) for p, f in lib if getter(f) is not None]
    pick = max(pool, key=lambda x: x[1]) if z < 0 else min(pool, key=lambda x: x[1])
    text = [f"# This week's lesson: {name}", "",
            f"Your tracks average {a:.1f}, the music you collect averages {l:.1f} ({z:+.1f} standard deviations). That is your biggest measured gap.", "",
            f"Study this: `{pick[0]}` ({pick[1]:.1f}). Listen to it next to one of your own tracks at matched volume.", "",
            "Questions to answer in your own words (then add them with `crate studio note`):",
            f"1. What is making that track sit {'higher' if z < 0 else 'lower'} on this measure than yours: sounds chosen, layering, EQ, arrangement?",
            "2. Where in the track does it change, and what triggers the change?",
            "3. What is one thing you would try in your next session?", "", teardown(Path(pick[0]), dict(next(f for p, f in lib if p == pick[0])))]
    return "\n".join(text)

def note_add(con, title: str, body: str, track: str | None = None):
    con.execute("INSERT INTO notes(ts,title,body,track_path) VALUES(?,?,?,?)", (time.time(), title, body, track)); con.commit()

def notes_markdown(con) -> str:
    rows = con.execute("SELECT * FROM notes ORDER BY ts DESC").fetchall()
    return "\n\n".join(f"## {time.strftime('%Y-%m-%d', time.localtime(r['ts']))}: {r['title']}\n{r['body']}" + (f"\n(track: {r['track_path']})" if r["track_path"] else "") for r in rows) or "No notes yet."
