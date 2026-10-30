"""Audio analysis used for teardowns and reference comparison.
Tempo uses long-lag autocorrelation of the onset envelope. Plain beat trackers are often several BPM off on club
music, while the repeat period of 4 to 32 beats pins it to a fraction of a BPM."""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np

BANDS = {"sub 20-60": (20, 60), "bass 60-250": (60, 250), "low-mid 250-500": (250, 500), "mid 500-2k": (500, 2000),
         "high-mid 2-6k": (2000, 6000), "high 6-12k": (6000, 12000), "air 12-20k": (12000, 20000)}
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

def load(path: Path, sr: int = 44100, max_seconds: float | None = None):
    import librosa
    y, _ = librosa.load(str(path), sr=sr, mono=False, duration=max_seconds)
    if y.ndim == 1: y = np.stack([y, y])
    return y[:2]

def _onset_env(mono, sr, hop=256):
    import librosa
    return librosa.onset.onset_strength(y=mono, sr=sr, hop_length=hop, aggregate=np.median), sr / hop

def estimate_tempo(mono: np.ndarray, sr: int, lo: float = 70, hi: float = 180) -> dict:
    env, fps = _onset_env(mono, sr)
    x = env - env.mean(); n = len(x)
    if n < fps * 8: return dict(bpm=None, confidence=0.0)
    f = np.fft.rfft(x, 2 * n); ac = np.fft.irfft(f * np.conj(f))[:n]; ac /= ac[0] + 1e-12
    lags = np.arange(int(fps * 60 / hi), int(fps * 60 / lo))
    prior = np.exp(-0.5 * (np.log2((60 * fps / lags) / 120) / 0.7) ** 2)
    base_lag = lags[int(np.argmax(ac[lags] * (0.6 + 0.4 * prior)))]
    est = []
    for k in (4, 8, 16, 32):
        c = k * base_lag; w = max(3, int(c * 0.03))
        if c + w >= n - 2: break
        seg = ac[c - w: c + w]; i = int(np.argmax(seg)) + c - w
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
        est.append((60 * k * fps / (i + d), float(ac[i])))
    if not est: return dict(bpm=round(60 * fps / base_lag, 2), confidence=float(ac[base_lag]))
    bpm = float(np.median([e[0] for e in est]))
    return dict(bpm=round(bpm, 2), confidence=round(float(np.mean([e[1] for e in est])), 3))

def estimate_key(mono: np.ndarray, sr: int) -> dict:
    import librosa
    h = librosa.effects.harmonic(mono[: sr * 240])
    c = librosa.feature.chroma_cqt(y=h, sr=sr).mean(1)
    scores = []
    for i in range(12):
        scores.append((float(np.corrcoef(c, np.roll(_MAJ, i))[0, 1]), f"{NOTES[i]} major"))
        scores.append((float(np.corrcoef(c, np.roll(_MIN, i))[0, 1]), f"{NOTES[i]} minor"))
    scores.sort(reverse=True)
    return dict(key=scores[0][1], runner_up=scores[1][1], margin=round(scores[0][0] - scores[1][0], 3),
                note="major/minor is a coin flip when the margin is small" if scores[0][0] - scores[1][0] < 0.05 else "")

def band_balance(mono: np.ndarray, sr: int) -> dict:
    import librosa
    S = np.abs(librosa.stft(mono, n_fft=4096, hop_length=2048)) ** 2
    fr = librosa.fft_frequencies(sr=sr, n_fft=4096)
    p = S.mean(1); tot = p.sum() + 1e-20
    return {k: round(10 * math.log10(p[(fr >= a) & (fr < b)].sum() / tot + 1e-12), 1) for k, (a, b) in BANDS.items() if b <= sr / 2}

def loudness(stereo: np.ndarray, sr: int) -> dict:
    import pyloudnorm as pln
    y = stereo.T
    try: lufs = float(pln.Meter(sr).integrated_loudness(y))
    except Exception: lufs = float("nan")
    pk = float(np.abs(y).max()); rms = float(np.sqrt((y ** 2).mean()))
    return dict(lufs=round(lufs, 1), sample_peak_db=round(20 * math.log10(pk + 1e-12), 1), crest_db=round(20 * math.log10((pk + 1e-12) / (rms + 1e-12)), 1))

def stereo_stats(stereo: np.ndarray, sr: int) -> dict:
    from scipy.signal import butter, sosfiltfilt
    L, R = stereo; M, S = (L + R) / 2, (L - R) / 2
    width = 20 * math.log10((np.sqrt((S ** 2).mean()) + 1e-12) / (np.sqrt((M ** 2).mean()) + 1e-12))
    sos = butter(4, 120, btype="low", fs=sr, output="sos")
    lo_l, lo_r = sosfiltfilt(sos, L), sosfiltfilt(sos, R)
    corr = float(np.corrcoef(lo_l, lo_r)[0, 1]) if lo_l.std() > 1e-9 and lo_r.std() > 1e-9 else 1.0
    return dict(width_db=round(max(-60.0, width), 1), low_end_correlation=round(corr, 3))

def sections(mono: np.ndarray, sr: int, bpm: float) -> list[dict]:
    """Bar-level energy map. Boundaries where level or low-end changes by 3 dB+ against the previous four bars."""
    import librosa
    from scipy.signal import butter, sosfiltfilt
    beat = 60 / bpm; bar = 4 * beat
    env, fps = _onset_env(mono, sr)
    t = np.arange(len(env)) / fps
    best = max(((float(np.interp(np.arange(p, len(mono) / sr, beat), t, env).mean()), p) for p in np.arange(0, beat, 0.01)))[1]
    nb = int((len(mono) / sr - best) / bar)
    if nb < 4: return []
    low = sosfiltfilt(butter(4, 150, btype="low", fs=sr, output="sos"), mono)
    def db(x): return 20 * math.log10(float(np.sqrt((x ** 2).mean())) + 1e-9)
    feats = []
    for i in range(nb):
        a, b = int((best + i * bar) * sr), int((best + (i + 1) * bar) * sr)
        feats.append((db(mono[a:b]), db(low[a:b])))
    feats = np.array(feats); cuts = [0]
    for i in range(4, nb):
        ref = np.median(feats[max(0, i - 4): i], axis=0)
        if np.any(np.abs(feats[i] - ref) >= 3.0) and i - cuts[-1] >= 2: cuts.append(i)
    cuts.append(nb); top = feats[:, 0].max(); out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        lvl, lo = feats[a:b].mean(axis=0)
        out.append(dict(start=round(best + a * bar, 1), end=round(best + b * bar, 1), bars=b - a, level_db=round(float(lvl), 1), low_db=round(float(lo), 1),
                        feel="full" if lvl > top - 2 else "mid" if lvl > top - 6 else "sparse"))
    return out

def analyze(path: Path, max_seconds: float | None = 360) -> dict:
    import librosa
    st = load(path, 44100, max_seconds); sr = 44100; mono = st.mean(0)
    m22 = librosa.resample(mono, orig_sr=sr, target_sr=22050)
    tempo = estimate_tempo(m22, 22050)
    f = dict(duration=round(len(mono) / sr, 1), tempo=tempo, key=estimate_key(m22, 22050), bands=band_balance(mono, sr),
             **loudness(st, sr), **stereo_stats(st, sr))
    f["sections"] = sections(m22, 22050, tempo["bpm"]) if tempo.get("bpm") and tempo["confidence"] > 0.15 else []
    return f
