from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  path TEXT PRIMARY KEY, artist TEXT, albumartist TEXT, album TEXT, title TEXT, year INTEGER,
  label TEXT, genre TEXT, track_no INTEGER, disc_no INTEGER, codec TEXT, lossless INTEGER,
  bitrate INTEGER, sample_rate INTEGER, bit_depth INTEGER, duration REAL,
  quick_hash TEXT, size INTEGER, mtime REAL, features TEXT, scanned_at REAL);
CREATE INDEX IF NOT EXISTS idx_tracks_hash ON tracks(quick_hash);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, run_id TEXT, src TEXT, dst TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY, artist TEXT, artist_mbid TEXT, release TEXT, release_year TEXT, label TEXT,
  country TEXT, tags TEXT, why TEXT, fit REAL, obscurity REAL, score REAL, listeners INTEGER,
  status TEXT DEFAULT 'new', created REAL, UNIQUE(artist_mbid));
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, candidate_id INTEGER, mode TEXT, facts TEXT, take TEXT, text TEXT,
  draft_text TEXT, status TEXT, issues TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS voice(id INTEGER PRIMARY KEY, text TEXT, weight REAL DEFAULT 1, source TEXT, created REAL);
CREATE TABLE IF NOT EXISTS avoid(word TEXT PRIMARY KEY, drafts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, ts REAL, title TEXT, body TEXT, track_path TEXT);
"""

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
