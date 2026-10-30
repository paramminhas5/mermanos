import json, re
from pathlib import Path
import pytest
from conftest import make_flac
from crate import cli, config as C
from test_library import messy
from test_voice_posts import SEEDS

@pytest.fixture
def home(cfg, monkeypatch):
    (cfg.home / "config.toml").write_text(f'library_root = "{cfg.library_root}"\ninbox = "{cfg.inbox}"\nown_music_dir = "{cfg.own_music_dir}"\ncontact = "t@example.com"\n')
    (cfg.voice_dir / "posts.txt").write_text("\n---\n".join(SEEDS))
    return cfg

def run(capsys, *args):
    cli.main(list(args)); return capsys.readouterr().out

def test_whole_workflow_through_the_cli(home, capsys, monkeypatch):
    messy(home.library_root)
    assert "new" in run(capsys, "scan")
    assert "tracks" in run(capsys, "report")
    out = run(capsys, "organize"); assert "Dry run" in out and (home.library_root / "dl").exists()
    run(capsys, "organize", "--apply"); assert (home.library_root / "Floating Points/Elaenia (2015)/01 - Nespole.flac").exists()
    run(capsys, "organize", "--undo"); assert (home.library_root / "dl/01.flac").exists()
    # ingest a purchase
    make_flac(home.inbox / "p.flac", artist="Obscure Guy", album="Obscure LP", title="Z", tracknumber="1", date="2003")
    assert '"move": 1' in run(capsys, "ingest")
    run(capsys, "ingest", "--apply"); assert (home.library_root / "Obscure Guy/Obscure LP (2003)/01 - Z.flac").exists()
    assert "Floating Points" in run(capsys, "taste")
    # candidate -> want -> wantlist -> post
    from crate import db
    con = db.connect(home.db_path)
    con.execute("INSERT INTO candidates(artist,artist_mbid,release,release_year,label,country,tags,why,listeners,score,status,created) VALUES('Nobody Known','mx','Odd EP','2011','Small Co','DE','idm',?,?,0.5,'new',0)", (json.dumps(["on Small Co, same label as X"]), 8)); con.commit()
    assert "Nobody Known" in run(capsys, "candidates")
    run(capsys, "want", "1"); run(capsys, "wantlist")
    wl = (home.reports_dir / "wantlist.md").read_text(); assert "Nobody Known" in wl and "bandcamp.com/search" in wl
    cid = con.execute("SELECT id FROM candidates").fetchone()[0]
    assert "post_" in run(capsys, "post", "new", str(cid))
    pf = home.queue_dir / "post_0001.md"; pf.write_text(re.sub(r"(## TAKE[^\n]*\n)", r"\1ordered it before the second listen\n", pf.read_text(), count=1))
    assert "ordered it before the second listen" in run(capsys, "post", "finalize", "1")
    assert "lint clean" in run(capsys, "post", "approve", "1")
    assert "Nobody Known" in run(capsys, "post", "export")
    assert '"n": 7' in run(capsys, "voice", "show")   # 6 seeds + the post you approved

def test_weekly_report_runs_offline_pieces(home, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_clients", lambda cfg, con: (None, None, None, None))
    import crate.discover as D; monkeypatch.setattr(D, "discover", lambda *a, **k: [])
    messy(home.library_root)
    out = run(capsys, "weekly")
    assert "Weekly crate report" in out and "## Inbox" in out and list(home.reports_dir.glob("weekly_*.md"))

def test_teardown_command(home, capsys, tmp_path):
    import numpy as np, soundfile as sf
    from test_studio import club_loop
    y = club_loop(126.0, bars=16); p = tmp_path / "t.wav"; sf.write(p, np.stack([y, y], 1), 44100)
    out = run(capsys, "studio", "teardown", str(p)); assert "Tempo 126" in out
