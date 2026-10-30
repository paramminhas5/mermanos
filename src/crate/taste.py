"""Taste profile built from what you actually own, plus a seeds file for artists you love but don't have."""
from __future__ import annotations
import json, math, statistics
from collections import Counter
from .util import norm

SKIP = {"", "various artists", "unknown", "unknown artist"}

def build(con, cfg) -> dict:
    rows = con.execute("SELECT artist,albumartist,album,label,genre,year FROM tracks").fetchall()
    tracks, albums = Counter(), {}
    names: dict[str, str] = {}
    labels, genres, decades = Counter(), Counter(), Counter()
    for r in rows:
        a = r["albumartist"] or r["artist"]
        k = norm(a)
        if k in SKIP: continue
        names.setdefault(k, a); tracks[k] += 1
        albums.setdefault(k, set()).add(norm(r["album"]))
        if r["label"]: labels[r["label"]] += 1
        for g in (r["genre"] or "").replace(";", "/").split("/"):
            if g.strip(): genres[g.strip().lower()] += 1
        if r["year"]: decades[f"{r['year'] // 10 * 10}s"] += 1
    weights = {k: math.sqrt(tracks[k]) + len(albums[k]) for k in tracks}
    seeds = []
    if cfg.seeds_file.exists():
        seeds = [l.strip() for l in cfg.seeds_file.read_text().splitlines() if l.strip() and not l.startswith("#")]
    floor = statistics.median(weights.values()) if weights else 3.0
    for line in list(seeds):
        name, _, w = line.partition("|")          # "Name | weight" sets an explicit weight, plain "Name" gets the floor
        name = name.strip(); k = norm(name); names.setdefault(k, name)
        try: weights[k] = max(weights.get(k, 0), float(w))
        except ValueError: weights[k] = max(weights.get(k, 0), floor, 3.0)
        seeds[seeds.index(line)] = name
    ranked = sorted(((names[k], round(w, 2)) for k, w in weights.items()), key=lambda x: -x[1])
    prof = dict(artists=ranked, labels=labels.most_common(25), genres=genres.most_common(25), decades=sorted(decades.items()),
                tracks=len(rows), seeds=seeds)
    (cfg.home / "taste.json").write_text(json.dumps(prof, indent=1))
    return prof

def explain(prof: dict) -> str:
    out = [f"{prof['tracks']} tracks, {len(prof['artists'])} artists ({len(prof['seeds'])} from your seeds file)", ""]
    out.append("Most weight: " + ", ".join(a for a, _ in prof["artists"][:15]))
    if prof["labels"]: out.append("Labels you collect: " + ", ".join(f"{l} ({n})" for l, n in prof["labels"][:10]))
    if prof["genres"]: out.append("Tagged genres: " + ", ".join(f"{g} ({n})" for g, n in prof["genres"][:10]))
    if prof["decades"]: out.append("Eras: " + ", ".join(f"{d} ({n})" for d, n in prof["decades"]))
    return "\n".join(out)
