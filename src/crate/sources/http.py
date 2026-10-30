from __future__ import annotations
import hashlib, json, time
from urllib.parse import urlparse
import requests

MIN_INTERVAL = {"musicbrainz.org": 1.1, "api.listenbrainz.org": 0.4, "ws.audioscrobbler.com": 0.25, "api.discogs.com": 1.2}

class Http:
    """Cached, rate-limited JSON client. Everything is cached 30 days in sqlite so reruns are fast and polite."""
    def __init__(self, con, user_agent: str, session=None, ttl: float = 30 * 86400, intervals: dict | None = None):
        self.con, self.ua, self.ttl = con, user_agent, ttl
        self.s = session or requests.Session()
        self.intervals = MIN_INTERVAL if intervals is None else intervals
        self._last: dict[str, float] = {}
        self.calls = 0

    def _key(self, method, url, params, payload):
        raw = json.dumps([method, url, sorted((params or {}).items()), payload], sort_keys=True, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()

    def _wait(self, url):
        host = urlparse(url).netloc
        gap = self.intervals.get(host, 0) - (time.time() - self._last.get(host, 0))
        if gap > 0: time.sleep(gap)
        self._last[host] = time.time()

    def request(self, method: str, url: str, params=None, payload=None, headers=None):
        key = self._key(method, url, params, payload)
        row = self.con.execute("SELECT value,ts FROM cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row["ts"] < self.ttl:
            return json.loads(row["value"])
        h = {"User-Agent": self.ua, "Accept": "application/json", **(headers or {})}
        last_err = None
        for attempt in range(4):
            self._wait(url); self.calls += 1
            try:
                r = self.s.request(method, url, params=params, json=payload, headers=h, timeout=30)
            except requests.RequestException as e:
                last_err = e; time.sleep(2 * (attempt + 1)); continue
            if r.status_code in (429, 503):
                time.sleep(min(30, 3 * (attempt + 1) ** 2)); last_err = RuntimeError(f"{r.status_code} from {url}"); continue
            if r.status_code == 404: data = None
            elif r.status_code >= 400: raise RuntimeError(f"{r.status_code} from {url}: {r.text[:200]}")
            else: data = r.json()
            self.con.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(data), time.time())); self.con.commit()
            return data
        raise RuntimeError(f"gave up on {url}: {last_err}")

    def get(self, url, params=None, headers=None): return self.request("GET", url, params=params, headers=headers)
    def post(self, url, payload, headers=None): return self.request("POST", url, payload=payload, headers=headers)
