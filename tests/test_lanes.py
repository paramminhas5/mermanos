import json, time
from crate import lanes

RAW = {"counts": {"pending": 4, "published": 12, "artists": 300, "ccd_events": 3, "rsvps": 37, "signups": 32},
       "runs": [{"job": "scrape", "ok": False, "started_at": "2026-10-30T20:30:00Z", "error": "boom"}, {"job": "scrape", "ok": True, "started_at": "2026-10-29T20:30:00Z"},
                {"job": "expire", "ok": True, "started_at": "2026-10-30T21:30:00Z"}],
       "build": [{"area": "seo", "title": "Fix sitemap", "status": "blocked"}, {"area": "ui", "title": "Done thing", "status": "done"}],
       "ccd_events": [{"title": "Night One", "event_date": "2999-01-01", "venue": "V", "published": True}, {"title": "Old", "event_date": "2001-01-01", "published": True}],
       "pending": [{"contact": "secret@example.com"}]}

def test_summary_is_safe_and_lists_what_needs_you():
    s = lanes.summarize_ccd(RAW)
    assert s["counts"]["pending"] == 4 and [e["title"] for e in s["upcoming"]] == ["Night One"]
    assert s["failed"][0]["job"] == "scrape" and any("4 scraped" in n for n in s["needs_you"]) and any("Fix sitemap" in n for n in s["needs_you"])
    assert "secret@example.com" not in json.dumps(s)

class FakeResp:
    def __init__(self, d): self.d = d
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return json.dumps(self.d).encode()

def test_collect_needs_config_then_works(cfg, monkeypatch):
    for k in ("CCD_SUPABASE_URL", "CCD_ANON_KEY", "CCD_OPS_TOKEN"): monkeypatch.delenv(k, raising=False)
    assert lanes.collect(cfg)["ccd"]["status"] == "not configured"
    (cfg.home / "lanes.env").write_text("CCD_SUPABASE_URL=https://x.supabase.co\nCCD_ANON_KEY=a\nCCD_OPS_TOKEN=t\n")
    seen = {}
    def opener(req, timeout=0): seen["body"] = req.data; seen["url"] = req.full_url; return FakeResp(RAW)
    out = lanes.collect(cfg, opener)["ccd"]
    assert out["status"] == "ok" and seen["url"].endswith("/rpc/ops_snapshot") and json.loads(seen["body"]) == {"p_token": "t"}
    assert lanes.collect(cfg, lambda *a, **k: (_ for _ in ()).throw(OSError("net")))["ccd"]["status"] == "error"
