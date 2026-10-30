import gzip, json, os, time
from crate import ableton, daily, db

def make_als(path, bpm=126, tracks=2, clips=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    x = '<Ableton Creator="Ableton Live 12"><LiveSet><MasterTrack><Tempo><Manual Value="%s"/></Tempo></MasterTrack>' % bpm
    x += "".join("<AudioTrack Id='%d'/>" % i for i in range(tracks)) + "".join("<AudioClip Id='%d'/>" % i for i in range(clips)) + "</LiveSet></Ableton>"
    path.write_bytes(gzip.compress(x.encode()))

def test_read_set_and_latest_per_project(tmp_path):
    make_als(tmp_path / "Alpha Project/alpha.als", bpm=131.5, tracks=3, clips=9)
    make_als(tmp_path / "Alpha Project/Backup/alpha [old].als")           # backups ignored
    make_als(tmp_path / "Empty Project/e.als", clips=1)                   # untouched sets dropped
    old = tmp_path / "Beta Project/beta.als"; make_als(old, bpm=100); os.utime(old, (time.time() - 5 * 86400,) * 2)
    rows = ableton.latest_per_project([tmp_path])
    assert [r["project"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0]["bpm"] == 131.5 and rows[0]["tracks"] == 3 and rows[0]["clips"] == 9 and rows[1]["days_ago"] == 5

def test_daily_build_state_html_and_no_dashes(cfg, con, tmp_path):
    cfg.ableton_dirs = [tmp_path]
    for i, b in enumerate([95, 120, 121, 122, 120]):
        p = tmp_path / f"P{i} Project/p{i}.als"; make_als(p, bpm=b); os.utime(p, (time.time() - i * 86400,) * 2)
    for n in range(3):
        con.execute("INSERT INTO candidates(artist,artist_mbid,release,release_year,label,why,score,status) VALUES(?,?,?,?,?,?,?, 'new')",
                    (f"A{n}", f"m{n}", "R", "2025", "Frank Music", json.dumps(["on Frank Music, same label as X"]), 1 - n / 10))
    con.commit()
    st = daily.build(cfg, con)
    assert st["headline"]["finds_waiting"] == 3 and st["headline"]["latest_bpm"] == 95 and st["lane"] == "merman"
    topics = [t["topic"] for t in st["today"]["talk"]]
    assert "Frank Music" in topics and any("95" in t for t in topics)      # label cluster + tempo shift prompts
    page = daily.render(st)
    assert "Merman OS" in page and "A0" in page and "—" not in json.dumps(st["today"]["talk"]) and "–" not in json.dumps(st["today"]["talk"])
    out = daily.write(cfg, st)
    assert out.exists() and json.loads((cfg.home / "state.json").read_text())["schema"] == 1


def test_listen_mix_puts_new_releases_first(cfg, con):
    yr = int(time.strftime("%Y"))
    for i, y in enumerate([1996, 1997, 1998, yr, yr - 1]):
        con.execute("INSERT INTO candidates(artist,artist_mbid,release,release_year,label,why,score,status) VALUES(?,?,?,?,?,?,?, 'new')",
                    (f"A{i}", f"m{i}", "R", str(y), "L", "[]", 1 - i / 10))
    con.commit()
    cfg.ableton_dirs = []
    listen = daily.build(cfg, con)["today"]["listen"]
    assert [f["artist"] for f in listen[:2]] == ["A3", "A4"] and len(listen) == 5


def test_publish_strips_paths_and_writes_online_copy(cfg, con, tmp_path):
    import subprocess
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"]); subprocess.run(["git", "-C", str(repo), "config", "user.email", "a@b.c"]); subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"])
    cfg.ableton_dirs = [tmp_path / "ab"]
    make_als(tmp_path / "ab/X Project/x.als", bpm=100, clips=8)
    st = daily.build(cfg, con)
    assert "path" in st["studio"][0]
    msg = daily.publish(cfg, st, repo, push=False)
    assert msg == "committed (not pushed)"
    assert "path" not in json.loads((repo / "mermanos" / "state.json").read_text())["studio"][0]
    assert "class=act" not in (repo / "mermanos" / "index.html").read_text() and str(tmp_path) not in (repo / "mermanos" / "index.html").read_text()
    assert daily.publish(cfg, st, repo, push=False) == "online copy already up to date"
