import numpy as np, soundfile as sf
from crate import analyze as A, studio

SR = 44100

def club_loop(bpm=126.0, bars=32, key_freq=98.0, quiet_first=8):
    beat = 60 / bpm; n = int(SR * beat * 4 * bars); y = np.zeros(n)
    for b in range(bars * 4):
        s = int(b * beat * SR)
        t = np.arange(int(0.15 * SR)) / SR
        kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-t * 30)) * t) * np.exp(-t * 18)
        amp = 0.15 if b < quiet_first * 4 else 0.9
        y[s:s + len(kick)] += amp * kick[: len(y) - s]
        h = int((b + 0.5) * beat * SR); hat = np.random.default_rng(b).standard_normal(int(0.03 * SR)) * np.exp(-np.arange(int(0.03 * SR)) / 300)
        y[h:h + len(hat)] += 0.2 * hat[: len(y) - h]
    t = np.arange(n) / SR
    y += 0.12 * (np.sin(2 * np.pi * key_freq * t) + 0.8 * np.sin(2 * np.pi * key_freq * 1.498 * t))   # fifth
    return y / np.abs(y).max() * 0.8

def test_tempo_is_accurate_to_a_fraction_of_a_bpm():
    for bpm in (126.0, 133.5, 100.0):
        y = club_loop(bpm).astype(np.float32)
        import librosa
        m = librosa.resample(y, orig_sr=SR, target_sr=22050)
        est = A.estimate_tempo(m, 22050)
        assert abs(est["bpm"] - bpm) < 0.4, (bpm, est)

def test_full_analysis_and_teardown_find_the_drop(tmp_path):
    y = club_loop(126.0)
    p = tmp_path / "loop.wav"; sf.write(p, np.stack([y, y], 1), SR)
    f = A.analyze(p)
    assert abs(f["tempo"]["bpm"] - 126.0) < 0.4
    assert f["low_end_correlation"] > 0.99 and f["width_db"] == -60.0   # mono source, clamped
    assert len(f["sections"]) >= 2
    drop = next(s for s in f["sections"][1:] if s["feel"] == "full")
    assert abs(drop["start"] - 8 * 4 * 60 / 126) < 2.0      # louder section starts about bar 8
    md = studio.teardown(p, f)
    assert "126" in md and "Arrangement map" in md

def test_compare_flags_big_differences():
    base = dict(duration=200, tempo={"bpm": 126, "confidence": .5}, key={"key": "G minor", "runner_up": "G major", "margin": .1, "note": ""},
                lufs=-9.0, sample_peak_db=-0.5, crest_db=9.0, width_db=-6.0, low_end_correlation=0.98,
                bands={b: -20.0 for b in A.BANDS}, sections=[])
    mine = {**base, "lufs": -14.0, "bands": {**base["bands"], "high-mid 2-6k": -28.0}}
    md = studio.compare([mine], [base])
    assert "high-mid 2-6k: 8.0 dB lighter" in md and "5.0 LU below" in md
