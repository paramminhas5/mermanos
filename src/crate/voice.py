"""Your voice: measured from your own writing, enforced by a linter. Nothing here invents taste."""
from __future__ import annotations
import re, statistics
from collections import Counter
from .util import norm

STOP = set("a an and are as at be but by for from has have i if in is it its me my of on or so that the their there this to was we were with you your just got really very".split())
DASHES = ("—", "–", "―", " -- ")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
BANNED = ["hidden gem", "underrated gem", "gem of a", "dive into", "deep dive", "delve", "tapestry", "testament to", "vibrant", "sonic landscape",
          "sonic journey", "sonic palette", "journey", "must-listen", "must listen", "masterclass", "game-changer", "game changer", "unleash",
          "immersive", "immerse", "ethereal", "mesmeriz", "mesmeris", "captivating", "stunning", "seamless", "elevate", "nestled", "in the realm of",
          "in a world where", "look no further", "buckle up", "whether you're", "whether you are", "excited to share", "check this out",
          "stumbled upon", "stumbled across", "came across", "genre-defying", "genre-bending", "pushing the boundaries", "pushes the boundaries",
          "absolutely", "incredible", "a must", "treat for", "feast for", "sonic", "crème de la crème", "rabbit hole", "obsessed"]
PATTERNS = [(re.compile(r"\bnot just\b.{0,60}\bbut\b", re.I | re.S), "'not just X but Y' construction"),
            (re.compile(r"\bit'?s not\b.{0,50}\bit'?s\b", re.I | re.S), "'it's not X, it's Y' construction"),
            (re.compile(r"\bhere'?s (why|what|the thing)\b", re.I), "'here's why' lead-in"),
            (re.compile(r"\b(\w+), (\w+),? and (\w+)\b"), "list of three (check it is really three things)")]

def split_posts(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*---+\s*\n", text) if p.strip()]

def load_samples(cfg, con) -> list[tuple[str, float]]:
    out = []
    if cfg.voice_dir.exists():
        for f in sorted(cfg.voice_dir.glob("*.txt")):
            out += [(p, 1.0) for p in split_posts(f.read_text())]
    out += [(r["text"], r["weight"]) for r in con.execute("SELECT text,weight FROM voice")]
    return out

def profile(samples: list[tuple[str, float]]) -> dict:
    texts = [t for t, _ in samples]
    if not texts: return dict(n=0)
    words = [len(re.findall(r"\w+", t)) for t in texts]
    sents = [len(re.findall(r"\w+", s)) for t in texts for s in re.split(r"[.!?\n]+", t) if s.strip()]
    first = Counter((re.findall(r"\w+", t.lower()) or [""])[0] for t in texts)
    vocab = Counter(w for t in texts for w in re.findall(r"[a-z']+", t.lower()) if w not in STOP and len(w) > 2)
    n = len(texts)
    return dict(n=n, median_words=statistics.median(words), mean_words=round(statistics.fmean(words), 1),
                sentence_words=round(statistics.fmean(sents), 1) if sents else 0,
                lowercase_start=round(sum(t[:1].islower() for t in texts) / n, 2),
                exclaim=round(sum(t.count("!") for t in texts) / n, 2), question=round(sum(t.count("?") for t in texts) / n, 2),
                hashtags=round(sum(t.count("#") for t in texts) / n, 2), emoji=round(sum(len(EMOJI.findall(t)) for t in texts) / n, 2),
                line_breaks=round(sum(t.count("\n") for t in texts) / n, 2), dashes=sum(any(d in t for d in DASHES) for t in texts),
                openers=first.most_common(5), vocab=[w for w, _ in vocab.most_common(40)])

def lint(text: str, prof: dict | None = None, facts: dict | None = None, avoid: set[str] | None = None) -> list[str]:
    issues, low = [], text.lower()
    for d in DASHES:
        if d in text: issues.append("error: contains a dash character (em/en dash). Use a full stop, comma or new line.")
    if re.search(r"\s-\s", text): issues.append("warn: spaced hyphen used like a dash")
    fact_text = " ".join(str(v) for v in (facts or {}).values()).lower()
    for b in BANNED:
        if b in low and b not in fact_text: issues.append(f"error: stock phrase '{b}'")
    for rx, msg in PATTERNS:
        if rx.search(text): issues.append(f"warn: {msg}")
    for w in (avoid or ()):
        if re.search(rf"\b{re.escape(w)}\b", low): issues.append(f"warn: '{w}' is a word you keep cutting from drafts")
    p = prof or {}
    if p.get("n", 0) >= 5:
        if text.count("!") > max(1, p["exclaim"] * 2): issues.append("warn: more exclamation marks than you normally use")
        if p["hashtags"] == 0 and "#" in text: issues.append("warn: hashtags (you don't use them)")
        if p["emoji"] == 0 and EMOJI.search(text): issues.append("warn: emoji (you don't use them)")
        if len(re.findall(r"\w+", text)) > 2 * p["median_words"] + 10: issues.append("warn: much longer than your usual post")
    if facts:
        key = [norm(v) for v in (facts.get("artist"), facts.get("release")) if v]
        if key and not any(k and k in norm(text) for k in key): issues.append("error: post never names the artist or release")
    return issues

def has_errors(issues: list[str]) -> bool: return any(i.startswith("error") for i in issues)
