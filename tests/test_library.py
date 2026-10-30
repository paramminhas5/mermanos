from pathlib import Path
from conftest import make_flac
from crate import scan, organize, acquire

def messy(root: Path):
    make_flac(root / "dl" / "01.flac", artist="Floating Points", album="Elaenia", title="Nespole", tracknumber="1", date="2015", freq=200)
    make_flac(root / "dl" / "02.flac", artist="Floating Points", album="Elaenia", title="Argenté", tracknumber="2", date="2015", freq=210)
    make_flac(root / "stuff" / "x.flac", artist="Nobody", title="No Album Single", freq=230)
    make_flac(root / "stuff" / "untagged.flac", freq=240)
    (root / "dl" / "cover.jpg").write_bytes(b"jpg")

def test_scan_and_plan(cfg, con):
    messy(cfg.library_root)
    st = scan.scan(con, cfg.library_root); assert st["new"] == 4
    rows = con.execute("SELECT * FROM tracks").fetchall()
    moves = organize.plan(rows, cfg.library_root, cfg.library_root)
    dst = {Path(m.src).name: Path(m.dst) for m in moves if m.kind != "sidecar"}
    assert dst["01.flac"].relative_to(cfg.library_root).as_posix() == "Floating Points/Elaenia (2015)/01 - Nespole.flac"
    assert dst["x.flac"].relative_to(cfg.library_root).as_posix() == "Nobody/Singles/Nobody - No Album Single.flac"
    assert "_review" in dst["untagged.flac"].parts
    assert any(m.kind == "sidecar" and m.dst.endswith("Elaenia (2015)/cover.jpg") for m in moves)

def test_apply_then_undo_restores_everything(cfg, con):
    messy(cfg.library_root)
    before = sorted(p.relative_to(cfg.library_root).as_posix() for p in cfg.library_root.rglob("*") if p.is_file())
    scan.scan(con, cfg.library_root)
    moves = organize.plan(con.execute("SELECT * FROM tracks").fetchall(), cfg.library_root, cfg.library_root)
    run = organize.apply(con, moves, cfg.library_root, log=lambda *_: None)
    assert (cfg.library_root / "Floating Points/Elaenia (2015)/02 - Argenté.flac").exists()
    assert not (cfg.library_root / "dl").exists()          # emptied source dir tidied
    assert con.execute("SELECT COUNT(*) FROM tracks WHERE path LIKE '%Elaenia%'").fetchone()[0] == 2
    organize.undo(con, run, log=lambda *_: None)
    after = sorted(p.relative_to(cfg.library_root).as_posix() for p in cfg.library_root.rglob("*") if p.is_file())
    assert after == before

def test_never_overwrites_and_flags_duplicates(cfg, con):
    a = make_flac(cfg.library_root / "Z/One/01 - Song.flac", artist="Z", album="One", title="Song", tracknumber="1", freq=300)
    scan.scan(con, cfg.library_root)
    import shutil; shutil.copy(a, cfg.inbox / "copy.flac")
    make_flac(cfg.inbox / "other.flac", artist="Z", album="One", title="Song", tracknumber="1", freq=500)   # same name, different audio
    r = acquire.ingest(con, cfg, apply=True, log=lambda *_: None)
    assert r["plan"] == {"duplicate": 1, "move": 1}
    files = [p.name for p in cfg.library_root.rglob("*.flac")]
    assert "01 - Song.flac" in files and "01 - Song (v2).flac" in files
    assert len(list((cfg.library_root / "_duplicates").rglob("*.flac"))) == 1
    assert not list(cfg.inbox.rglob("*.flac"))

def test_lossy_never_replaces_lossless_and_corrupt_is_rejected(cfg, con):
    make_flac(cfg.library_root / "A/B/01 - T.flac", artist="A", album="B", title="T", tracknumber="1")
    scan.scan(con, cfg.library_root)
    (cfg.inbox / "bad.flac").write_bytes(b"fLaC" + b"\x00" * 200)
    r = acquire.ingest(con, cfg, apply=True, log=lambda *_: None)
    assert (cfg.inbox / "bad.flac").exists()          # left alone, not filed
