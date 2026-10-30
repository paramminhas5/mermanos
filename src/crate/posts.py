"""Post drafting that keeps you the author.
scaffold (default): the agent supplies verified facts, YOU write the take, the agent formats and lints it.
draft: an LLM may reword YOUR take in YOUR voice. It is never allowed to supply opinions or invent facts, and nothing posts itself."""
from __future__ import annotations
import difflib, json, re, time
from pathlib import Path
from . import voice

EXAMPLE_LIMIT = 14

def facts_for(c) -> dict:
    f = dict(artist=c["artist"], release=c["release"], year=c["release_year"], label=c["label"], country=c["country"], tags=c["tags"])
    if c["listeners"] is not None: f["listeners"] = f'{c["listeners"]:,} people on ListenBrainz'
    return {k: v for k, v in f.items() if v}

def _path(cfg, pid: int) -> Path: return cfg.queue_dir / f"post_{pid:04d}.md"

def _write(cfg, pid, facts, take, text, status, issues):
    body = ["# Post {} ({})".format(pid, status), "", "## FACTS (from MusicBrainz and ListenBrainz. Delete a line to stop it being used)"]
    body += [f"- {k}: {v}" for k, v in facts.items()]
    body += ["", "## TAKE (your words, 1 to 3 lines. This is the post. Leave empty and nothing gets written)", take or "", "",
             "## TEXT (generated from the above. Edit freely, then run `crate post approve {}`)".format(pid), text or "", ""]
    if issues: body += ["## LINT"] + [f"- {i}" for i in issues]
    cfg.queue_dir.mkdir(parents=True, exist_ok=True); _path(cfg, pid).write_text("\n".join(body))

def _read(cfg, pid: int) -> dict:
    t = _path(cfg, pid).read_text()
    def sec(name):
        m = re.search(rf"^## {name}[^\n]*\n(.*?)(?=^## |\Z)", t, re.S | re.M)
        return m.group(1).strip() if m else ""
    facts = {}
    for l in sec("FACTS").splitlines():
        m = re.match(r"-\s*(\w+):\s*(.+)", l)
        if m: facts[m.group(1)] = m.group(2).strip()
    return dict(facts=facts, take=sec("TAKE"), text=sec("TEXT"))

def new(con, cfg, cand_id: int) -> int:
    c = con.execute("SELECT * FROM candidates WHERE id=?", (cand_id,)).fetchone()
    if not c: raise SystemExit(f"no candidate #{cand_id}")
    facts = facts_for(c)
    cur = con.execute("INSERT INTO posts(candidate_id,mode,facts,take,text,status,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                      (cand_id, cfg.post_mode, json.dumps(facts), "", "", "scaffold", time.time(), time.time()))
    con.commit(); _write(cfg, cur.lastrowid, facts, "", "", "scaffold", [])
    return cur.lastrowid

def _avoid(con) -> set[str]: return {r["word"] for r in con.execute("SELECT word FROM avoid WHERE drafts>=2")}

def _facts_line(f: dict) -> str:
    a = f.get("artist", ""); r = f.get("release"); y = f.get("year"); l = f.get("label")
    s = a + (f", {r}" if r else "") + (f" ({y})" if y else "") + (f", {l}" if l else "")
    return s + "."

def _llm(cfg, samples, facts, take, issues=None) -> str:
    try: import anthropic
    except ImportError: raise SystemExit("pip install anthropic to use draft mode")
    if not cfg.anthropic_key: raise SystemExit("set ANTHROPIC_API_KEY to use draft mode")
    ex = "\n\n---\n\n".join(t for t, w in sorted(samples, key=lambda x: -x[1])[:EXAMPLE_LIMIT])
    system = ("You ghostwrite short music posts for one specific person. Below are real posts he wrote. Match his rhythm, casing, punctuation, "
              "length and vocabulary exactly. Never use em dashes or en dashes. No hashtags or emoji unless his examples use them. "
              "Use ONLY the facts given and the take he gave. Do not add opinions, adjectives about the sound, backstory or comparisons he did not "
              "provide. Keep his take close to verbatim. Output the post text only.\n\nHIS POSTS:\n\n" + ex)
    user = "FACTS:\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items()) + f"\n\nHIS TAKE:\n{take}\n"
    if issues: user += "\nYour previous attempt had these problems, fix them:\n" + "\n".join(issues)
    r = anthropic.Anthropic(api_key=cfg.anthropic_key).messages.create(model=cfg.model, max_tokens=400, system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if getattr(b, "text", None)).strip()

def finalize(con, cfg, pid: int, llm=None) -> tuple[str, list[str]]:
    d = _read(cfg, pid)
    if not d["take"]:
        raise SystemExit(f"{_path(cfg, pid)}: write your take first. The post is built around what you actually thought of the record.")
    samples = voice.load_samples(cfg, con); prof = voice.profile(samples); avoid = _avoid(con)
    mode = cfg.post_mode
    if mode == "draft":
        issues = None; text = ""
        for _ in range(3):
            text = (llm or _llm)(cfg, samples, d["facts"], d["take"], issues)
            issues = voice.lint(text, prof, d["facts"], avoid)
            if not voice.has_errors(issues): break
    else:
        text = d["take"].strip() + "\n\n" + _facts_line(d["facts"])
        issues = voice.lint(text, prof, d["facts"], avoid)
    con.execute("UPDATE posts SET take=?,text=?,draft_text=?,status='draft',issues=?,updated=? WHERE id=?", (d["take"], text, text, json.dumps(issues), time.time(), pid))
    con.commit(); _write(cfg, pid, d["facts"], d["take"], text, "draft", issues)
    return text, issues

def approve(con, cfg, pid: int, force: bool = False) -> list[str]:
    d = _read(cfg, pid)
    if not d["text"]: raise SystemExit("nothing in TEXT yet, run `crate post finalize` first")
    samples = voice.load_samples(cfg, con)
    issues = voice.lint(d["text"], voice.profile(samples), d["facts"], _avoid(con))
    if voice.has_errors(issues) and not force:
        _write(cfg, pid, d["facts"], d["take"], d["text"], "draft", issues)
        raise SystemExit("not approved, fix these in the file or pass --force:\n" + "\n".join(issues))
    row = con.execute("SELECT draft_text FROM posts WHERE id=?", (pid,)).fetchone()
    draft = (row["draft_text"] if row else "") or ""
    if draft and draft != d["text"]:                      # learn from what you cut
        keep = set(re.findall(r"[a-z']{4,}", d["text"].lower())) | set(re.findall(r"[a-z']{4,}", " ".join(d["facts"].values()).lower()))
        removed = set(re.findall(r"[a-z']{4,}", draft.lower())) - keep
        for w in removed:
            con.execute("INSERT INTO avoid(word,drafts) VALUES(?,1) ON CONFLICT(word) DO UPDATE SET drafts=drafts+1", (w,))
    con.execute("INSERT INTO voice(text,weight,source,created) VALUES(?,?,?,?)", (d["text"], 2.0, "edit", time.time()))
    con.execute("UPDATE posts SET text=?,status='approved',issues=?,updated=? WHERE id=?", (d["text"], json.dumps(issues), time.time(), pid))
    con.commit(); _write(cfg, pid, d["facts"], d["take"], d["text"], "approved", issues)
    return issues

def approved(con) -> list[tuple[int, str]]:
    return [(r["id"], r["text"]) for r in con.execute("SELECT id,text FROM posts WHERE status='approved' ORDER BY id")]
