from __future__ import annotations
import re, unicodedata, hashlib, os
from pathlib import Path

AUDIO_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".alac", ".wv", ".ape"}
SIDECAR_EXT = {".jpg", ".jpeg", ".png", ".cue", ".log", ".m3u", ".m3u8", ".pdf", ".nfo"}
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

def norm(s: str | None) -> str:
    """Loose key for comparing names across sources: lowercase, no accents, no punctuation, no leading 'the'."""
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^the\s+", "", s.strip())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()

def safe_name(s: str, limit: int = 120) -> str:
    s = unicodedata.normalize("NFC", s or "").strip()
    s = _BAD.sub("_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:limit].strip(" .") or "_"

def quick_hash(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, os.SEEK_END); h.update(f.read(65536))
    return h.hexdigest()

def first_int(v) -> int | None:
    if v is None: return None
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None
