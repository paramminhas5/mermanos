"""A tiny fake of MusicBrainz + ListenBrainz so discovery can be tested offline and deterministically."""
class Resp:
    def __init__(self, data, code=200): self._d, self.status_code, self.text = data, code, str(data)
    def json(self): return self._d

ARTISTS = {"Seed One": "seed1", "Seed Two": "seed2"}
TAGS = {"seed1": ["idm", "ambient"], "seed2": ["idm", "electronic"], "obscure": ["idm", "ambient"], "famous": ["idm", "electronic"], "bigact": ["idm"], "lonely": []}
# label id -> (name, size, [(release title, date, [(artist id, name)])])
LABELS = {
    "L1": ("Tiny Label", 10, [("Seed Rec A", "2001", [("seed1", "Seed One")]), ("Obscure LP", "2003", [("obscure", "Obscure Guy")]), ("Famous EP", "2004", [("famous", "Famous Guy")])]),
    "L3": ("Small Imprint", 12, [("Seed Rec B", "2005", [("seed2", "Seed Two")]), ("Famous 2", "2006", [("famous", "Famous Guy")])]),
    "L4": ("Micro Records", 8, [("Seed Rec C", "2007", [("seed1", "Seed One")]), ("Famous 3", "2008", [("famous", "Famous Guy")])]),
    "L2": ("Giant Label", 5000, [("Seed Rec D", "2009", [("seed1", "Seed One")]), ("Big Act LP", "2010", [("bigact", "Big Label Artist")])]),
}
SEED_LABELS = {"seed1": ["L1", "L4", "L2"], "seed2": ["L3"]}
USERS = {"obscure": 12, "famous": 200000, "bigact": 5, "lonely": 0}

class FakeSession:
    def __init__(self): self.log = []
    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.log.append((method, url)); p = params or {}
        if "listenbrainz" in url:
            return Resp([dict(artist_mbid=m, total_listen_count=USERS.get(m, 0) * 20, total_user_count=USERS[m]) for m in json["artist_mbids"] if m in USERS])
        if url.endswith("/artist/"):
            name = p["query"].split('"')[1]
            return Resp({"artists": [dict(id=ARTISTS[name], name=name, score=100, country="GB", tags=[])]} if name in ARTISTS else {"artists": []})
        if "/artist/" in url:
            mid = url.rsplit("/", 1)[1]
            nm = {v: k for k, v in ARTISTS.items()}.get(mid, mid)
            rels = [dict(type="collaboration", artist=dict(id="lonely", name="Lonely Collaborator"))] if mid == "seed2" else []
            return Resp(dict(name=nm, country="GB", genres=[], tags=[dict(name=t, count=5 - i) for i, t in enumerate(TAGS.get(mid, []))], relations=rels))
        if url.endswith("/release"):
            if "artist" in p:
                rs = [dict(title=t, date=d, **{"label-info": [dict(label=dict(id=lid, name=LABELS[lid][0]))]}) for lid in SEED_LABELS.get(p["artist"], []) for t, d, a in LABELS[lid][2] if any(x[0] == p["artist"] for x in a)]
                return Resp({"releases": rs})
            lid = p["label"]; name, size, rels = LABELS[lid]
            if p.get("limit") == 1: return Resp({"release-count": size, "releases": []})
            return Resp({"release-count": size, "releases": [dict(title=t, date=d, **{"artist-credit": [dict(artist=dict(id=i, name=n)) for i, n in arts]}) for t, d, arts in rels]})
        return Resp(None, 404)
