import re, json, pytest
from crate import voice, posts

SEEDS = ["found this at the weekend. proper strange", "new one from the label i keep going back to", "picked this up on a whim, been on repeat since",
         "tiny pressing, no one talks about it", "this one sounds like a cassette left in a car", "slow, a bit broken, good for 2am"]
def seed_voice(con):
    for t in SEEDS: con.execute("INSERT INTO voice(text,weight,source,created) VALUES(?,1,'seed',0)", (t,))
    con.commit()

def cand(con, **kw):
    d = dict(artist="Obscure Guy", artist_mbid="m1", release="Obscure LP", release_year="2003", label="Tiny Label", country="GB", tags="idm", why="[]", listeners=12)
    d.update(kw)
    con.execute("INSERT INTO candidates(artist,artist_mbid,release,release_year,label,country,tags,why,listeners,status,created) VALUES(?,?,?,?,?,?,?,?,?,'new',0)",
                (d["artist"], d["artist_mbid"], d["release"], d["release_year"], d["label"], d["country"], d["tags"], d["why"], d["listeners"]))
    con.commit(); return con.execute("SELECT id FROM candidates ORDER BY id DESC").fetchone()[0]

def set_take(cfg, pid, take):
    p = posts._path(cfg, pid); p.write_text(re.sub(r"(## TAKE[^\n]*\n)", lambda m: m.group(1) + take + "\n", p.read_text(), count=1))

def test_lint_catches_ai_tells_and_dashes():
    bad = "A hidden gem — truly a sonic journey, not just beautiful but haunting."
    issues = voice.lint(bad)
    assert voice.has_errors(issues)
    assert any("dash" in i for i in issues) and any("hidden gem" in i for i in issues) and any("not just" in i for i in issues)
    assert voice.lint("slow and a bit broken. good for 2am.") == []

def test_banned_word_allowed_when_it_is_the_actual_title():
    assert not voice.has_errors(voice.lint("Journey by Nobody is on repeat", facts=dict(artist="Nobody", release="Journey")))

def test_lint_requires_naming_the_music():
    assert voice.has_errors(voice.lint("been on repeat all week", facts=dict(artist="Obscure Guy", release="Obscure LP")))

def test_profile_reflects_your_habits(cfg, con):
    seed_voice(con)
    p = voice.profile(voice.load_samples(cfg, con))
    assert p["n"] == 6 and p["lowercase_start"] == 1.0 and p["exclaim"] == 0 and p["hashtags"] == 0
    iss = voice.lint("Great record! Amazing! Wow! Love it! #newmusic", p)
    assert any("exclamation" in i for i in iss) and any("hashtag" in i for i in iss)

def test_scaffold_requires_your_take_and_keeps_it_verbatim(cfg, con):
    seed_voice(con); pid = posts.new(con, cfg, cand(con))
    assert "Obscure Guy" in posts._path(cfg, pid).read_text()
    with pytest.raises(SystemExit): posts.finalize(con, cfg, pid)                  # no take, no post
    take = "bought this on a hunch, the second track keeps looping in my head"
    set_take(cfg, pid, take)
    text, issues = posts.finalize(con, cfg, pid)
    assert text.startswith(take) and "Obscure Guy, Obscure LP (2003), Tiny Label." in text and issues == []
    assert posts.approve(con, cfg, pid) == []
    assert posts.approved(con)[0][0] == pid
    assert con.execute("SELECT COUNT(*) FROM voice WHERE source='edit'").fetchone()[0] == 1   # approved post joins your voice samples

def test_approve_blocks_ai_sounding_edits_unless_forced(cfg, con):
    seed_voice(con); pid = posts.new(con, cfg, cand(con)); set_take(cfg, pid, "good one"); posts.finalize(con, cfg, pid)
    p = posts._path(cfg, pid); p.write_text(p.read_text().replace("good one", "a hidden gem — Obscure Guy"))
    with pytest.raises(SystemExit): posts.approve(con, cfg, pid)
    posts.approve(con, cfg, pid, force=True)

def test_draft_mode_retries_until_lint_is_clean_and_never_without_a_take(cfg, con):
    cfg.post_mode = "draft"; seed_voice(con); pid = posts.new(con, cfg, cand(con))
    with pytest.raises(SystemExit): posts.finalize(con, cfg, pid, llm=lambda *a: "x")
    set_take(cfg, pid, "second track keeps looping in my head")
    replies = iter(["Obscure Guy is a hidden gem — a sonic journey", "second track keeps looping in my head. Obscure Guy, Obscure LP, Tiny Label."])
    calls = []
    def fake_llm(cfg, samples, facts, take, issues=None):
        calls.append(issues); return next(replies)
    text, issues = posts.finalize(con, cfg, pid, llm=fake_llm)
    assert len(calls) == 2 and calls[0] is None and any("hidden gem" in i for i in calls[1]) and issues == []
    assert "—" not in text

def test_it_learns_words_you_keep_cutting(cfg, con):
    cfg.post_mode = "draft"; seed_voice(con)
    for n in range(2):
        pid = posts.new(con, cfg, cand(con, artist=f"Artist {n}", artist_mbid=f"m{n+5}", release=f"Rel {n}"))
        set_take(cfg, pid, "keeps looping in my head")
        posts.finalize(con, cfg, pid, llm=lambda *a: "keeps looping in my head, a properly textured record. Artist %d" % n)
        p = posts._path(cfg, pid); p.write_text(p.read_text().replace(", a properly textured record", ""))
        posts.approve(con, cfg, pid)
    assert "textured" in posts._avoid(con)
    assert any("textured" in i for i in voice.lint("a textured record. Obscure Guy", avoid=posts._avoid(con)))
