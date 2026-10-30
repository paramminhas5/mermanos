from __future__ import annotations
from ..util import norm

BASE = "https://musicbrainz.org/ws/2"
NO_LABEL = {"157afde4-4bf5-4039-8ad2-5a15acc85ada"}          # [no label]
VARIOUS = {"89ad4ac3-39f7-470e-963a-56509c546377", "f731ccc4-e22a-43af-a747-64213329e088", "33cf029c-63b0-41a0-9855-be2a3665fb3b"}  # VA, [anonymous], [unknown]

class MusicBrainz:
    def __init__(self, http): self.h = http

    def find_artist(self, name: str) -> dict | None:
        """Exact-name match. Tries a quoted query, then a plain one (apostrophes and odd punctuation break the quoted form)."""
        for q in (f'artist:"{name}"', name.replace("\u2019", "'").replace("'", " ")):
            d = self.h.get(f"{BASE}/artist/", {"query": q, "fmt": "json", "limit": 10})
            for a in (d or {}).get("artists", []):
                if a.get("score", 0) >= 80 and norm(a["name"]) == norm(name):
                    return dict(mbid=a["id"], name=a["name"], country=a.get("country"), tags=[t["name"] for t in sorted(a.get("tags", []), key=lambda t: -t.get("count", 0))[:6]])
        return None

    def artist_info(self, mbid: str) -> dict:
        d = self.h.get(f"{BASE}/artist/{mbid}", {"inc": "artist-rels+tags+genres", "fmt": "json"}) or {}
        tags = [t["name"] for t in sorted(d.get("genres", []) + d.get("tags", []), key=lambda t: -t.get("count", 0))]
        seen, uniq = set(), []
        for t in tags:
            if t not in seen: seen.add(t); uniq.append(t)
        rels = []
        for r in d.get("relations", []):
            a = r.get("artist")
            if a and r.get("type") in {"member of band", "collaboration", "subgroup", "founder", "supporting musician"} and a["id"] not in VARIOUS:
                rels.append(dict(type=r["type"], mbid=a["id"], name=a["name"]))
        return dict(mbid=mbid, name=d.get("name"), country=d.get("country"), tags=uniq[:8], rels=rels)

    def artist_releases(self, mbid: str, limit: int = 100) -> list[dict]:
        d = self.h.get(f"{BASE}/release", {"artist": mbid, "inc": "labels", "fmt": "json", "limit": limit}) or {}
        out, seen = [], set()
        for r in d.get("releases", []):
            labels = [(li["label"]["id"], li["label"]["name"]) for li in r.get("label-info", []) if li.get("label")]
            k = (norm(r["title"]), tuple(l[0] for l in labels))
            if k in seen: continue
            seen.add(k); out.append(dict(title=r["title"], date=r.get("date", ""), labels=labels))
        return out

    def label_size(self, label_id: str) -> int:
        d = self.h.get(f"{BASE}/release", {"label": label_id, "fmt": "json", "limit": 1}) or {}
        return int(d.get("release-count", 0))

    def label_releases(self, label_id: str, pages: int = 2) -> list[dict]:
        out = []
        for p in range(pages):
            d = self.h.get(f"{BASE}/release", {"label": label_id, "inc": "artist-credits", "fmt": "json", "limit": 100, "offset": p * 100}) or {}
            for r in d.get("releases", []):
                arts = [(c["artist"]["id"], c["artist"]["name"]) for c in r.get("artist-credit", []) if isinstance(c, dict) and c.get("artist")]
                out.append(dict(title=r["title"], date=r.get("date", ""), artists=arts))
            if len(d.get("releases", [])) < 100: break
        return out
