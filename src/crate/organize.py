"""Plan-first library organiser. Nothing moves until --apply, nothing is ever deleted, every move is journalled and undoable."""
from __future__ import annotations
import shutil, time, uuid
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from .util import SIDECAR_EXT, AUDIO_EXT, norm, safe_name

VA = "Various Artists"

@dataclass
class Move:
    src: str
    dst: str
    kind: str   # move | review | duplicate | sidecar
    note: str = ""

def _album_groups(rows):
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((str(Path(r["path"]).parent), norm(r["album"])), []).append(r)
    return groups

def plan(rows, dest_root: Path, src_root: Path, existing_hashes: dict[str, str] | None = None) -> list[Move]:
    """rows: sqlite rows to place under dest_root. existing_hashes: quick_hash -> path for files already in dest_root."""
    dest_root = dest_root.resolve(); src_root = src_root.resolve()
    existing_hashes = existing_hashes or {}
    moves: list[Move] = []; taken: dict[str, str] = {}
    run_tag = time.strftime("%Y%m%d")
    for (srcdir, _), grp in sorted(_album_groups(rows).items()):
        artists = Counter(norm(r["artist"]) for r in grp if r["artist"])
        multi_disc = any((r["disc_no"] or 1) > 1 for r in grp)
        year = (Counter(r["year"] for r in grp if r["year"]).most_common(1) or [(None, 0)])[0][0]
        has_album = bool(grp[0]["album"])
        aa_group = None
        if has_album:      # singles/untagged files share an empty-album group, so only real albums get a group-level artist
            aa_group = next((r["albumartist"] for r in grp if r["albumartist"]), None)
            if not aa_group:
                top = Counter(r["artist"] for r in grp if r["artist"]).most_common(1)
                aa_group = VA if len(artists) >= 4 else (top[0][0] if top else None)
        placed_dirs = set()
        for r in sorted(grp, key=lambda x: ((x["disc_no"] or 1), (x["track_no"] or 0), x["path"])):
            src = Path(r["path"]); ext = src.suffix.lower()
            aa = aa_group or r["albumartist"] or r["artist"]
            if not (r["artist"] and r["title"]) or not aa:
                dst = dest_root / "_review" / src.relative_to(src_root) if src_root in src.parents else dest_root / "_review" / src.name
                moves.append(Move(str(src), str(dst), "review", "missing artist or title tag")); continue
            album = r["album"] or "Singles"
            folder = dest_root / safe_name(aa) / safe_name(f"{album} ({year})" if (year and r["album"]) else album)
            num = f'{(r["disc_no"] or 1)}-' if multi_disc and r["track_no"] else ""
            num += f'{r["track_no"]:02d} - ' if r["track_no"] else ""
            who = f'{r["artist"]} - ' if aa == VA or not r["album"] else ""
            dst = folder / (safe_name(f'{num}{who}{r["title"]}') + ext)
            if dst == src: continue
            h = r["quick_hash"]
            if h in existing_hashes and Path(existing_hashes[h]) != src:
                dup = dest_root / "_duplicates" / run_tag / dst.relative_to(dest_root)
                moves.append(Move(str(src), str(dup), "duplicate", f"same content as {existing_hashes[h]}")); continue
            n = 1
            while (dst.exists() and dst != src) or str(dst) in taken:
                n += 1; dst = folder / (safe_name(f'{num}{who}{r["title"]}') + f" (v{n})" + ext)
            taken[str(dst)] = str(src)
            moves.append(Move(str(src), str(dst), "move")); placed_dirs.add(folder)
        # sidecars: only when the whole source folder went to one destination folder
        if len(placed_dirs) == 1:
            folder = next(iter(placed_dirs)); sd = Path(srcdir)
            if sd.exists() and all(Path(r["path"]).parent == sd for r in grp):
                audio_here = {p for p in sd.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT}
                if audio_here <= {Path(r["path"]) for r in rows}:
                    for p in sorted(sd.iterdir()):
                        if p.is_file() and p.suffix.lower() in SIDECAR_EXT and not (folder / p.name).exists():
                            moves.append(Move(str(p), str(folder / p.name), "sidecar"))
    return moves

def apply(con, moves: list[Move], src_root: Path, log=print) -> str:
    run_id = uuid.uuid4().hex[:8]; done = 0
    for m in moves:
        src, dst = Path(m.src), Path(m.dst)
        if not src.exists() or dst.exists(): log(f"skip (changed on disk): {src}"); continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        con.execute("INSERT INTO journal(run_id,src,dst,ts) VALUES(?,?,?,?)", (run_id, m.src, m.dst, time.time()))
        con.execute("UPDATE tracks SET path=? WHERE path=?", (m.dst, m.src)); done += 1
    con.commit()
    # tidy empty source folders (rmdir only succeeds on empty dirs, so this can never delete content)
    src_root = src_root.resolve()
    for d in sorted({Path(m.src).parent for m in moves}, key=lambda p: len(p.parts), reverse=True):
        while d != src_root and src_root in d.parents:
            try: d.rmdir()
            except OSError: break
            d = d.parent
    log(f"moved {done} files (run {run_id}). Undo with: crate organize --undo {run_id}")
    return run_id

def undo(con, run_id: str | None = None, log=print) -> int:
    if run_id is None:
        r = con.execute("SELECT run_id FROM journal ORDER BY id DESC LIMIT 1").fetchone()
        if not r: log("nothing to undo"); return 0
        run_id = r["run_id"]
    n = 0
    for j in con.execute("SELECT * FROM journal WHERE run_id=? ORDER BY id DESC", (run_id,)).fetchall():
        src, dst = Path(j["src"]), Path(j["dst"])
        if dst.exists() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(dst), str(src))
            con.execute("UPDATE tracks SET path=? WHERE path=?", (j["src"], j["dst"])); n += 1
        else: log(f"cannot restore {dst}")
    con.execute("DELETE FROM journal WHERE run_id=?", (run_id,)); con.commit()
    log(f"restored {n} files from run {run_id}")
    return n

def summarize(moves: list[Move]) -> dict:
    c = Counter(m.kind for m in moves); return dict(c)
