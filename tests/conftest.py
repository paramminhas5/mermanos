import numpy as np, pytest, soundfile as sf
from pathlib import Path
from mutagen.flac import FLAC
from crate import config as C, db

SR = 44100

def make_flac(path: Path, secs=8, freq=220.0, **tags):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(SR * secs)) / SR
    y = 0.2 * np.sin(2 * np.pi * freq * t) + 0.01 * np.random.default_rng(abs(hash((str(path), freq))) % 2**32).standard_normal(len(t))
    sf.write(path, np.stack([y, y], 1), SR, format="FLAC")
    f = FLAC(path)
    for k, v in tags.items(): f[k] = str(v)
    f.save()
    return path

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CRATE_HOME", str(tmp_path / "home"))
    home = C.init_home()
    c = C.load(home)
    c.library_root = tmp_path / "lib"; c.inbox = tmp_path / "inbox"; c.own_music_dir = tmp_path / "mine"
    for d in (c.library_root, c.inbox, c.own_music_dir): d.mkdir()
    return c

@pytest.fixture
def con(cfg): return db.connect(cfg.db_path)
