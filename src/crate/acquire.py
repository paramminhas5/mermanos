"""Getting music INTO the library. Purchases and legitimate downloads land in the inbox; this verifies, files and tracks them.
There is deliberately no downloader for streaming-service rips."""
from __future__ import annotations
import shutil, subprocess, time
from pathlib import Path
from urllib.parse import quote_plus
from . import scan as scanmod, organize
from .util import norm

def verify(path: Path) -> tuple[bool, str]:
    if path.suffix.lower() == ".flac" and shutil.which("flac"):
        r = subprocess.run(["flac", "-t", "-s", str(path)], capture_output=True, text=True)
        return (r.returncode == 0, r.stderr.strip()[:200] or "ok")
    t = scanmod.read_tags(path)
    if t is None: return False, "unreadable"
    if t["duration"] < 5: return False, f'suspiciously short ({t["duration"]:.1f}s)'
    return True, "ok"

def ingest(con, cfg, apply: bool = False, log=print) -> dict:
    inbox = cfg.inbox
    if not inbox.exists(): log(f"inbox {inbox} does not exist"); return {}
    scanmod.scan(con, inbox, log=log)
    rows = con.execute("SELECT * FROM tracks WHERE path LIKE ?", (str(inbox.resolve()) + "%",)).fetchall()
    good, bad = [], []
    for r in rows:
        ok, why = verify(Path(r["path"]))
        (good if ok else bad).append((r, why))
    lib = {r["quick_hash"]: r["path"] for r in con.execute("SELECT quick_hash,path FROM tracks WHERE path LIKE ?", (str(cfg.library_root.resolve()) + "%",))}
    lossless_keys = {(norm(r["artist"]), norm(r["title"])) for r in con.execute("SELECT artist,title FROM tracks WHERE lossless=1 AND path LIKE ?", (str(cfg.library_root.resolve()) + "%",))}
    lossy_have = {(norm(r["artist"]), norm(r["title"])) for r in con.execute("SELECT artist,title FROM tracks WHERE lossless=0 AND path LIKE ?", (str(cfg.library_root.resolve()) + "%",))}
    skipped, upgrades, keep = [], [], []
    for r, _ in good:
        key = (norm(r["artist"]), norm(r["title"]))
        if not r["lossless"] and key in lossless_keys: skipped.append(r["path"]); continue
        if r["lossless"] and key in lossy_have: upgrades.append(f'{r["artist"]} - {r["title"]}')
        keep.append(r)
    moves = organize.plan(keep, cfg.library_root, inbox, lib)
    out = dict(inbox_files=len(rows), failed_verify=[(r["path"], w) for r, w in bad], lossy_dupe_of_lossless=skipped,
               lossless_upgrades=upgrades, plan=organize.summarize(moves), applied=False)
    if apply and moves:
        organize.apply(con, moves, inbox, log=log); out["applied"] = True
        mark_owned(con)
    return out

def mark_owned(con) -> int:
    have = {norm(r["a"]) for r in con.execute("SELECT artist a FROM tracks UNION SELECT albumartist FROM tracks") if r["a"]}
    n = 0
    for c in con.execute("SELECT id,artist FROM candidates WHERE status IN ('new','wanted')").fetchall():
        if norm(c["artist"]) in have:
            con.execute("UPDATE candidates SET status='owned' WHERE id=?", (c["id"],)); n += 1
    con.commit(); return n

def buy_links(artist: str, release: str | None = None) -> dict[str, str]:
    q = quote_plus(f"{artist} {release}".strip() if release else artist)
    return {"Bandcamp": f"https://bandcamp.com/search?q={q}", "Discogs": f"https://www.discogs.com/search/?q={q}&type=release",
            "Beatport": f"https://www.beatport.com/search?q={q}", "Qobuz": f"https://www.qobuz.com/us-en/search?q={q}"}

def export_wantlist(con, path: Path, include_new: int = 0) -> Path:
    import json
    rows = con.execute("SELECT * FROM candidates WHERE status='wanted' ORDER BY score DESC").fetchall()
    if include_new:
        rows += con.execute("SELECT * FROM candidates WHERE status='new' ORDER BY score DESC LIMIT ?", (include_new,)).fetchall()
    lines = [f"# Wantlist ({time.strftime('%Y-%m-%d')})", "", "Buy lossless where you can, then drop the files in your inbox and run `crate ingest --apply`.", ""]
    for c in rows:
        why = json.loads(c["why"] or "[]")
        lines.append(f'## {c["artist"]}' + (f' - {c["release"]}' if c["release"] else "") + f' [#{c["id"]}]')
        meta = " | ".join(x for x in (c["label"], c["release_year"], c["country"], c["tags"]) if x)
        if meta: lines.append(meta)
        lines += [f"- {w}" for w in why[:3]]
        lines.append("  ".join(f"[{k}]({v})" for k, v in buy_links(c["artist"], c["release"]).items()))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines))
    return path
