from __future__ import annotations
import math

def _clamp(x): return max(0.0, min(1.0, x))

class ListenBrainz:
    """Free popularity signal: how many distinct people have listened. Works without a token."""
    def __init__(self, http, token: str | None = None): self.h, self.token = http, token
    def artists(self, mbids: list[str]) -> dict[str, dict]:
        out = {}
        hdr = {"Authorization": f"Token {self.token}"} if self.token else None
        for i in range(0, len(mbids), 25):
            chunk = mbids[i:i + 25]
            data = self.h.post("https://api.listenbrainz.org/1/popularity/artist", {"artist_mbids": chunk}, headers=hdr) or []
            for row in data: out[row["artist_mbid"]] = dict(listens=row.get("total_listen_count") or 0, users=row.get("total_user_count") or 0)
            for m in chunk: out.setdefault(m, dict(listens=0, users=0))
        return out

class LastFm:
    def __init__(self, http, key: str): self.h, self.key = http, key
    def listeners(self, name: str) -> int | None:
        d = self.h.get("https://ws.audioscrobbler.com/2.0/", {"method": "artist.getinfo", "artist": name, "api_key": self.key, "format": "json"}) or {}
        try: return int(d["artist"]["stats"]["listeners"])
        except (KeyError, ValueError, TypeError): return None

class Discogs:
    """How many collectors own / want a release. Needs a free personal token (DISCOGS_TOKEN)."""
    def __init__(self, http, token: str): self.h, self.token = http, token
    def demand(self, artist: str, title: str) -> dict | None:
        hdr = {"Authorization": f"Discogs token={self.token}"}
        s = self.h.get("https://api.discogs.com/database/search", {"artist": artist, "release_title": title, "type": "release", "per_page": 3}, headers=hdr) or {}
        res = s.get("results") or []
        if not res: return None
        c = (res[0].get("community") or {})
        if "have" in c: return dict(have=c["have"], want=c.get("want", 0))
        r = self.h.get(f"https://api.discogs.com/releases/{res[0]['id']}", headers=hdr) or {}
        c = (r.get("community") or {})
        return dict(have=c.get("have", 0), want=c.get("want", 0)) if c else None

def obscurity(users: int | None = None, lastfm: int | None = None, discogs_have: int | None = None) -> tuple[float, str]:
    """1.0 = nobody has heard of it, 0.0 = everyone has. Averages whichever signals exist."""
    parts, notes = [], []
    if users is not None:
        parts.append(1 - _clamp(math.log10(1 + users) / 5.5)); notes.append(f"{users:,} ListenBrainz listener" + ("" if users == 1 else "s"))
    if lastfm is not None:
        parts.append(1 - _clamp(math.log10(1 + lastfm) / 6.5)); notes.append(f"{lastfm:,} Last.fm listeners")
    if discogs_have is not None:
        parts.append(1 - _clamp(math.log10(1 + discogs_have) / 4.0)); notes.append(f"{discogs_have:,} Discogs collectors")
    return (sum(parts) / len(parts), ", ".join(notes)) if parts else (0.5, "no popularity data")
