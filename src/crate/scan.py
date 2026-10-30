from __future__ import annotations
import time
from pathlib import Path
import mutagen
from .util import AUDIO_EXT, quick_hash, first_int

LOSSLESS = {"flac", "wav", "aiff", "alac", "wv", "ape"}

def _first(tags, *keys):
    for k in keys:
        try: v = tags.get(k)
        except Exception: v = None
        if v: return str(v[0]) if isinstance(v, (list, tuple)) else str(v)
    return None

def read_tags(path: Path) -> dict | None:
    try:
        f = mutagen.File(path, easy=True)
    except Exception:
        f = None
    if f is None or getattr(f, "info", None) is None:
        return None
    info, kind = f.info, type(f).__name__.lower()
    codec = {"flac": "flac", "mp3": "mp3", "easymp3": "mp3", "easymp4": "aac", "mp4": "aac", "oggvorbis": "vorbis",
             "oggopus": "opus", "wave": "wav", "aiff": "aiff", "wavpack": "wv", "monkeysaudio": "ape"}.get(kind, kind)
    if codec == "aac" and "alac" in str(getattr(info, "codec", "")).lower(): codec = "alac"
    tags = f.tags or {}
    date = _first(tags, "date", "originaldate", "year") or ""
    return dict(
        artist=_first(tags, "artist"), albumartist=_first(tags, "albumartist"), album=_first(tags, "album"),
        title=_first(tags, "title"), year=first_int(date[:4]) if date else None,
        label=_first(tags, "label", "organization", "publisher"), genre=_first(tags, "genre"),
        track_no=first_int(_first(tags, "tracknumber")), disc_no=first_int(_first(tags, "discnumber")),
        codec=codec, lossless=int(codec in LOSSLESS),
        bitrate=int(getattr(info, "bitrate", 0) or 0) // 1000,
        sample_rate=int(getattr(info, "sample_rate", 0) or 0),
        bit_depth=int(getattr(info, "bits_per_sample", 0) or 0),
        duration=float(getattr(info, "length", 0) or 0),
    )

def scan(con, root: Path, prune: bool = True, log=print) -> dict:
    root = root.resolve()
    stats = dict(seen=0, new=0, updated=0, unreadable=0, pruned=0)
    existing = {r["path"]: (r["size"], r["mtime"]) for r in con.execute("SELECT path,size,mtime FROM tracks WHERE path LIKE ?", (str(root) + "%",))}
    found = set()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXT or p.name.startswith("."):
            continue
        stats["seen"] += 1
        sp = str(p); found.add(sp)
        st = p.stat()
        if sp in existing and existing[sp] == (st.st_size, st.st_mtime):
            continue
        t = read_tags(p)
        if t is None:
            stats["unreadable"] += 1; log(f"unreadable: {p}"); continue
        t.update(path=sp, size=st.st_size, mtime=st.st_mtime, quick_hash=quick_hash(p), scanned_at=time.time(), features=None)
        cols = ",".join(t); qs = ",".join("?" * len(t))
        con.execute(f"INSERT OR REPLACE INTO tracks({cols}) VALUES({qs})", list(t.values()))
        stats["updated" if sp in existing else "new"] += 1
    if prune:
        for sp in set(existing) - found:
            con.execute("DELETE FROM tracks WHERE path=?", (sp,)); stats["pruned"] += 1
    con.commit()
    return stats

def quality_report(con, root: Path) -> dict:
    rows = con.execute("SELECT * FROM tracks WHERE path LIKE ?", (str(root.resolve()) + "%",)).fetchall()
    by_codec: dict[str, int] = {}
    for r in rows: by_codec[r["codec"]] = by_codec.get(r["codec"], 0) + 1
    albums: dict[tuple, list] = {}
    for r in rows:
        albums.setdefault(((r["albumartist"] or r["artist"] or "?"), r["album"] or "?"), []).append(r)
    upgrade = sorted(f"{a} - {b}" for (a, b), rs in albums.items() if rs and not all(x["lossless"] for x in rs))
    low = sorted({f'{r["artist"]} - {r["title"]} ({r["bitrate"]}k)' for r in rows if r["codec"] == "mp3" and 0 < r["bitrate"] < 192})
    untagged = [r["path"] for r in rows if not (r["artist"] and r["title"])]
    return dict(tracks=len(rows), by_codec=by_codec, albums=len(albums), lossless_pct=round(100 * sum(r["lossless"] for r in rows) / max(1, len(rows)), 1),
                albums_to_upgrade=upgrade, low_bitrate=low, untagged=untagged)
