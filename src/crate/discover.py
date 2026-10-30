"""Obscure-music discovery by graph walk, not by 'people also listened to'.

seed artists (your library) -> the small labels they put out records on -> everyone else on those labels,
plus collaborators and band members. Candidates are ranked by how close they sit to your taste AND how few people
have heard them. Every candidate carries the path that found it, so you can judge it instead of trusting a black box."""
from __future__ import annotations
import json, math, re, time
from collections import defaultdict
from .util import norm
from .sources.musicbrainz import NO_LABEL, VARIOUS
from .sources.popularity import obscurity

# radio shows, podcast series and mix series are filed as labels in MusicBrainz but make poor pivots
NOT_REAL_LABELS = re.compile(r"\b(fm|radio|podcast|mixmag|resident advisor|boiler room|nts|bbc|late ?night ?tales|dj-?kicks|fabric(live)?|essential mix|self[- ]released|not on label)\b", re.I)

def _year(d: str) -> str: return (d or "")[:4]

def discover(con, cfg, mb, lb, lastfm=None, discogs=None, prof=None, log=print) -> list[dict]:
    from . import taste
    prof = prof or taste.build(con, cfg)
    owned = {norm(a) for a, _ in prof["artists"]}
    seeds = prof["artists"][:cfg.seed_artists]
    if not seeds: log("No taste data yet. Scan a library or add names to seeds.txt first."); return []

    seed_meta, label_hits, cand = {}, defaultdict(lambda: dict(w=0.0, name="", seeds=[])), {}
    genre_w = defaultdict(float)
    for name, w in seeds:
        a = mb.find_artist(name)
        if not a: log(f"  (no MusicBrainz match for {name})"); continue
        info = mb.artist_info(a["mbid"]); seed_meta[a["mbid"]] = (name, w)
        for t in info["tags"]: genre_w[t] += w
        for rel in mb.artist_releases(a["mbid"]):
            for lid, lname in rel["labels"]:
                if lid in NO_LABEL: continue
                h = label_hits[lid]; h["w"] += w; h["name"] = lname
                if name not in h["seeds"]: h["seeds"].append(name)
        for r in info["rels"]:
            if norm(r["name"]) in owned: continue
            c = cand.setdefault(r["mbid"], dict(name=r["name"], ev=[], rel=[]))
            c["ev"].append((w * 0.6, f'{r["type"].replace("member of band", "in a band with")} {name}'))
    for g, n in prof["genres"]: genre_w[g] += n
    gmax = max(genre_w.values()) if genre_w else 1.0

    log(f"  {len(seed_meta)} seeds resolved, {len(label_hits)} labels in play")
    pivots = []
    for lid, h in sorted(label_hits.items(), key=lambda x: -x[1]["w"])[:cfg.pivots * 2]:
        if NOT_REAL_LABELS.search(h["name"]) or h["name"].lower() in {n.lower() for n in cfg.ignore_labels}: continue
        size = mb.label_size(lid)
        if 3 <= size <= cfg.max_label_size: pivots.append((lid, h, size))
    pivots = sorted(pivots, key=lambda p: -p[1]["w"] / math.log2(2 + p[2]))[:cfg.pivots]
    log(f"  digging through {len(pivots)} small labels")
    for lid, h, size in pivots:
        lw = h["w"] / math.log2(2 + size)
        for rel in mb.label_releases(lid):
            for amid, aname in rel["artists"]:
                if amid in VARIOUS or amid in seed_meta or norm(aname) in owned: continue
                c = cand.setdefault(amid, dict(name=aname, ev=[], rel=[]))
                if not any(l == lid for l, _ in c["rel"]):
                    c["ev"].append((lw, f'on {h["name"]} ({size} releases), the same label as {", ".join(h["seeds"][:2])}'))
                c["rel"].append((lid, dict(title=rel["title"], date=rel["date"], label=h["name"])))
    if not cand: log("  no candidates found"); return []

    for c in cand.values(): c["fit"] = sum(w for w, _ in c["ev"])
    top = sorted(cand.items(), key=lambda kv: -kv[1]["fit"])[: cfg.max_candidates * 4]
    fmax = top[0][1]["fit"] or 1.0
    pop = lb.artists([m for m, _ in top])
    e = 2.0 * cfg.obscurity          # dial 0 ignores popularity entirely, 1 squares it
    results = []
    for mbid, c in top:
        users = pop.get(mbid, {}).get("users")
        fm = lastfm.listeners(c["name"]) if lastfm else None
        rels = sorted(c["rel"], key=lambda x: x[1]["date"] or "9999")
        if cfg.since:   # recency mode: only releases from the window count, newest first
            rels = [x for x in reversed(rels) if _year(x[1]["date"]).isdigit() and int(_year(x[1]["date"])) >= cfg.since]
            if not rels: continue
        rep = rels[0][1] if rels else None
        dg = None
        if discogs and rep:
            try: d = discogs.demand(c["name"], rep["title"]); dg = d["have"] if d else None
            except Exception: dg = None
        obs, obs_note = obscurity(users, fm, dg)
        results.append(dict(mbid=mbid, c=c, obs=obs, obs_note=obs_note, users=users, rep=rep, fit=c["fit"] / fmax))
    results.sort(key=lambda r: -(r["fit"] * r["obs"] ** e))
    # keep the list varied: at most N per label, and one credit per release (a 3-artist release is one find, not three)
    known = {r["artist_mbid"] for r in con.execute("SELECT artist_mbid FROM candidates WHERE status!='new'")}   # wanted / owned / skipped
    cap = max(3, cfg.max_candidates // 8); per_label, seen_rel, chosen = defaultdict(int), set(), []
    for r in results:
        if r["mbid"] in known: continue
        lab = (r["rep"] or {}).get("label") or r["mbid"]
        rk = (norm((r["rep"] or {}).get("title", "")), lab) if r["rep"] else None
        if per_label[lab] >= cap or (rk and rk in seen_rel): continue
        per_label[lab] += 1; chosen.append(r)
        if rk: seen_rel.add(rk)
        if len(chosen) >= cfg.max_candidates: break
    out = []
    for r in chosen:
        info = mb.artist_info(r["mbid"])
        overlap = sum(genre_w.get(t, 0) for t in info["tags"][:5]) / (gmax * max(1, min(5, len(info["tags"])))) if info["tags"] else 0.35
        score = r["fit"] * (0.5 + 0.5 * min(1.0, overlap * 2)) * r["obs"] ** e
        ev = sorted(r["c"]["ev"], key=lambda x: -x[0])
        why, seen = [], set()
        for _, t in ev:
            if t not in seen: seen.add(t); why.append(t)
        why.append(r["obs_note"] + (" (almost no listening data, so this may just mean untracked)" if (r["users"] or 0) < 5 else ""))
        out.append(dict(artist=r["c"]["name"], artist_mbid=r["mbid"], release=(r["rep"] or {}).get("title"),
                        release_year=_year((r["rep"] or {}).get("date", "")), label=(r["rep"] or {}).get("label"),
                        country=info["country"], tags=", ".join(info["tags"][:4]), why=why, fit=round(r["fit"], 3),
                        obscurity=round(r["obs"], 3), score=round(score, 4), listeners=r["users"]))
    out.sort(key=lambda x: -x["score"])
    fresh = {o["artist_mbid"] for o in out}                      # drop last run's unreviewed suggestions that did not make this one
    for r in con.execute("SELECT id,artist_mbid FROM candidates WHERE status='new'").fetchall():
        if r["artist_mbid"] not in fresh: con.execute("DELETE FROM candidates WHERE id=?", (r["id"],))
    for o in out:
        con.execute("""INSERT INTO candidates(artist,artist_mbid,release,release_year,label,country,tags,why,fit,obscurity,score,listeners,status,created)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'new',?)
            ON CONFLICT(artist_mbid) DO UPDATE SET release=excluded.release,release_year=excluded.release_year,label=excluded.label,
              country=excluded.country,tags=excluded.tags,why=excluded.why,fit=excluded.fit,obscurity=excluded.obscurity,
              score=excluded.score,listeners=excluded.listeners""",
            (o["artist"], o["artist_mbid"], o["release"], o["release_year"], o["label"], o["country"], o["tags"], json.dumps(o["why"]),
             o["fit"], o["obscurity"], o["score"], o["listeners"], time.time()))
    con.commit()
    return out
