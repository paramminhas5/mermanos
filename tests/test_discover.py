import json
from conftest import make_flac
from fakes import FakeSession
from crate import scan, discover, taste
from crate.sources.http import Http
from crate.sources.musicbrainz import MusicBrainz
from crate.sources.popularity import ListenBrainz, obscurity

def build(cfg, con):
    make_flac(cfg.library_root / "Seed One/X/01 - a.flac", artist="Seed One", album="X", title="a", tracknumber="1", genre="idm")
    make_flac(cfg.library_root / "Seed Two/Y/01 - b.flac", artist="Seed Two", album="Y", title="b", tracknumber="1", genre="idm")
    scan.scan(con, cfg.library_root)
    http = Http(con, "test", session=FakeSession(), intervals={})
    return http, MusicBrainz(http), ListenBrainz(http)

def run(cfg, con, obscurity_dial):
    http, mb, lb = build(cfg, con); cfg.obscurity = obscurity_dial
    return http, discover.discover(con, cfg, mb, lb, log=lambda *_: None)

def test_default_dial_prefers_obscure_over_famous_and_explains_why(cfg, con):
    _, out = run(cfg, con, 0.8)
    names = [o["artist"] for o in out]
    assert names.index("Obscure Guy") < names.index("Famous Guy")
    assert "Big Label Artist" not in names          # only reachable through a 5000-release label
    assert "Seed One" not in names and "Seed Two" not in names
    ob = next(o for o in out if o["artist"] == "Obscure Guy")
    assert any("Tiny Label" in w for w in ob["why"]) and any("12 ListenBrainz listeners" in w for w in ob["why"])
    assert ob["release"] == "Obscure LP" and ob["label"] == "Tiny Label"

def test_dial_at_zero_lets_close_famous_artist_win(cfg, con):
    _, out = run(cfg, con, 0.0)
    assert out[0]["artist"] == "Famous Guy"

def test_collaborator_found_with_no_listening_data(cfg, con):
    _, out = run(cfg, con, 0.8)
    lone = next(o for o in out if o["artist"] == "Lonely Collaborator")
    assert any("collaboration" in w for w in lone["why"])

def test_results_persist_and_second_run_is_fully_cached(cfg, con):
    http, out = run(cfg, con, 0.8)
    calls = http.calls
    assert con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == len(out)
    con.execute("UPDATE candidates SET status='wanted' WHERE artist='Obscure Guy'"); con.commit()
    discover.discover(con, cfg, MusicBrainz(http), ListenBrainz(http), log=lambda *_: None)
    assert http.calls == calls
    assert con.execute("SELECT status FROM candidates WHERE artist='Obscure Guy'").fetchone()[0] == "wanted"   # rerun keeps your decisions

def test_owning_a_candidate_marks_it_owned(cfg, con):
    from crate import acquire
    run(cfg, con, 0.8)
    make_flac(cfg.library_root / "Obscure Guy/Obscure LP/01 - z.flac", artist="Obscure Guy", album="Obscure LP", title="z", tracknumber="1")
    scan.scan(con, cfg.library_root); assert acquire.mark_owned(con) == 1
    assert con.execute("SELECT status FROM candidates WHERE artist='Obscure Guy'").fetchone()[0] == "owned"

def test_obscurity_scale():
    assert obscurity(0)[0] == 1.0 and obscurity(155000)[0] < 0.1 and obscurity(None)[1] == "no popularity data"
    mid, note = obscurity(100, lastfm=2000, discogs_have=50); assert 0.4 < mid < 0.8 and "Discogs" in note


def test_label_cap_and_one_credit_per_release(cfg, con):
    import fakes
    # three artists share one release, and ten more crowd a single label
    fakes.LABELS["L1"][2].append(("Split Release", "2004", [("s1", "Split A"), ("s2", "Split B"), ("s3", "Split C")]))
    for i in range(10): fakes.LABELS["L1"][2].append((f"Crowd {i}", "2005", [(f"c{i}", f"Crowd Artist {i}")]))
    try:
        cfg.max_candidates = 8
        _, out = run(cfg, con, 0.8)
    finally:
        fakes.LABELS["L1"] = (fakes.LABELS["L1"][0], fakes.LABELS["L1"][1], fakes.LABELS["L1"][2][:3])
    assert sum(o["label"] == "Tiny Label" for o in out) <= 3
    assert sum(o["release"] == "Split Release" for o in out) <= 1


def test_skipped_never_returns_and_stale_suggestions_are_replaced(cfg, con):
    http, out = run(cfg, con, 0.8)
    con.execute("UPDATE candidates SET status='skipped' WHERE artist='Famous Guy'")
    con.execute("INSERT INTO candidates(artist,artist_mbid,status,score,created) VALUES('Stale One','stale',?,0.9,0)", ("new",)); con.commit()
    out2 = discover.discover(con, cfg, MusicBrainz(http), ListenBrainz(http), log=lambda *_: None)
    assert "Famous Guy" not in [o["artist"] for o in out2]
    names = {r[0] for r in con.execute("SELECT artist FROM candidates WHERE status='new'")}
    assert "Stale One" not in names and "Obscure Guy" in names
    assert con.execute("SELECT status FROM candidates WHERE artist='Famous Guy'").fetchone()[0] == "skipped"


def test_weighted_seeds_file(cfg, con):
    from crate import taste
    cfg.seeds_file.write_text("Alpha | 9\nBeta\n# c\n")
    prof = taste.build(con, cfg)
    w = dict(prof["artists"])
    assert w["Alpha"] == 9.0 and w["Beta"] >= 3.0 and prof["seeds"] == ["Alpha", "Beta"]
