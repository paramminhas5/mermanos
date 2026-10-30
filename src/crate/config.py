"""Config lives in ~/.crate/config.toml (override with CRATE_HOME). Secrets come from env vars only."""
from __future__ import annotations
import os
try:
    import tomllib
except ModuleNotFoundError:   # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE = '''# crate config
library_root = "~/Music/Library"      # organised library (lossless preferred)
inbox        = "~/Music/Inbox"        # drop purchased / downloaded files here
own_music_dir = "~/Music/My Tracks"   # your own productions (used by the studio module)
ableton_dirs = ["~/Music"]            # folders searched for Ableton projects (.als)
# publish_dir = "~/ParamOS"           # a git checkout of your ParamOS repo: `crate daily` pushes the online copy there
contact      = "you@example.com"      # sent in the User-Agent to MusicBrainz, as they ask

[discovery]
obscurity = 0.7        # 0 = ignore popularity, 1 = dig as deep as possible
max_label_size = 400   # labels with more releases than this are treated as too big to be a useful pivot
seed_artists = 25      # how many of your top artists to branch out from
max_candidates = 60
pivots = 40            # how many small labels to dig through
ignore_labels = []     # extra label names to never use as a pivot, e.g. ["Some Mix Series"]

[posts]
mode = "scaffold"      # scaffold = you write the take. draft = LLM drafts in your voice, you edit.
model = "claude-sonnet-5-5"
'''

@dataclass
class Config:
    home: Path
    library_root: Path
    inbox: Path
    own_music_dir: Path
    contact: str = "unset@example.com"
    obscurity: float = 0.7
    max_label_size: int = 400
    since: int = 0
    pivots: int = 40
    ableton_dirs: list = None
    publish_dir: Path | None = None
    seed_artists: int = 25
    max_candidates: int = 60
    ignore_labels: list = field(default_factory=list)
    post_mode: str = "scaffold"
    model: str = "claude-sonnet-5-5"
    lastfm_key: str | None = field(default=None, repr=False)
    discogs_token: str | None = field(default=None, repr=False)
    lb_token: str | None = field(default=None, repr=False)
    anthropic_key: str | None = field(default=None, repr=False)

    @property
    def db_path(self) -> Path: return self.home / "crate.db"
    @property
    def queue_dir(self) -> Path: return self.home / "queue"
    @property
    def voice_dir(self) -> Path: return self.home / "voice"
    @property
    def reports_dir(self) -> Path: return self.home / "reports"
    @property
    def seeds_file(self) -> Path: return self.home / "seeds.txt"

def home_dir() -> Path:
    return Path(os.environ.get("CRATE_HOME", Path.home() / ".crate")).expanduser()

def _p(s: str) -> Path: return Path(os.path.expanduser(s)).resolve()

def init_home(home: Path | None = None) -> Path:
    home = home or home_dir()
    for d in ("queue", "voice", "reports"):
        (home / d).mkdir(parents=True, exist_ok=True)
    cfg = home / "config.toml"
    if not cfg.exists(): cfg.write_text(TEMPLATE)
    seeds = home / "seeds.txt"
    if not seeds.exists():
        seeds.write_text("# artists you love but don't own yet, one per line. They count towards your taste profile.\n")
    return home

def load(home: Path | None = None) -> Config:
    home = home or home_dir()
    path = home / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    d, p = raw.get("discovery", {}), raw.get("posts", {})
    return Config(
        home=home,
        library_root=_p(raw.get("library_root", "~/Music/Library")),
        inbox=_p(raw.get("inbox", "~/Music/Inbox")),
        own_music_dir=_p(raw.get("own_music_dir", "~/Music/My Tracks")),
        contact=raw.get("contact", "unset@example.com"),
        obscurity=float(d.get("obscurity", 0.7)),
        max_label_size=int(d.get("max_label_size", 400)),
        seed_artists=int(d.get("seed_artists", 25)),
        max_candidates=int(d.get("max_candidates", 60)),
        ignore_labels=list(d.get("ignore_labels", [])),
        pivots=int(d.get("pivots", 40)),
        ableton_dirs=[_p(x) for x in raw.get("ableton_dirs", ["~/Music"])],
        publish_dir=_p(raw["publish_dir"]) if raw.get("publish_dir") else None,
        post_mode=p.get("mode", "scaffold"),
        model=p.get("model", "claude-sonnet-5-5"),
        lastfm_key=os.environ.get("LASTFM_API_KEY"),
        discogs_token=os.environ.get("DISCOGS_TOKEN"),
        lb_token=os.environ.get("LISTENBRAINZ_TOKEN"),
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
