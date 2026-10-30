"""Read Ableton Live sets (.als) without Live. A set is gzipped XML; we pull tempo, track and clip counts and the save time."""
from __future__ import annotations
import gzip, re, time
from pathlib import Path

AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a"}

def read_set(path: Path) -> dict | None:
    try: x = gzip.open(path, "rb").read().decode("utf8", "ignore")
    except Exception: return None
    t = re.search(r"<Tempo>.*?<Manual Value=\"([\d.]+)\"", x, re.S)
    return dict(file=path.name, project=_project_name(path), path=str(path), mtime=path.stat().st_mtime,
                bpm=round(float(t.group(1)), 1) if t else None,
                tracks=len(re.findall(r"<(?:AudioTrack|MidiTrack) ", x)),
                clips=len(re.findall(r"<(?:AudioClip|MidiClip) ", x)),
                ver=(re.search(r'Creator="([^"]+)"', x) or [None, None])[1])

def _project_name(p: Path) -> str:
    d = p.parent.name
    return d[:-8].strip() if d.endswith(" Project") else d

def find_sets(roots: list[Path], max_depth: int = 4) -> list[Path]:
    out = []
    for r in roots:
        if not r.exists(): continue
        base = len(r.resolve().parts)
        for p in r.rglob("*.als"):
            parts = p.resolve().parts
            if len(parts) - base > max_depth + 1: continue
            if "Backup" in parts or "Factory Packs" in parts or "Live Recordings" in parts or p.name.startswith("."): continue
            out.append(p)
    return out

def latest_per_project(roots: list[Path]) -> list[dict]:
    """One row per project folder: its most recently saved set. Newest first. Empty/untouched sets are dropped."""
    best: dict[str, dict] = {}
    for p in find_sets(roots):
        s = read_set(p)
        if not s or s["clips"] < 3: continue
        k = str(p.parent)
        if k not in best or s["mtime"] > best[k]["mtime"]: best[k] = s
    rows = sorted(best.values(), key=lambda s: -s["mtime"])
    for s in rows:
        s["date"] = time.strftime("%Y-%m-%d", time.localtime(s["mtime"]))
        s["days_ago"] = int((time.time() - s["mtime"]) // 86400)
        d = Path(s["path"]).parent
        s["bounces"] = sum(1 for f in d.iterdir() if f.suffix.lower() in AUDIO_EXT) if d.exists() else 0
    return rows
