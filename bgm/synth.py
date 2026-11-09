"""Synthesized instruments and drums (no samples needed)."""

import numpy as np

from .paths import SR
from .theory import midi_to_hz

_rng = np.random.default_rng(1234)


def _t(n):
    return np.arange(n, dtype=np.float32) / SR


def _stereo(x):
    x = x.astype(np.float32)
    return np.stack([x, x], axis=1)


def _release_env(n, hold_s, rel_s):
    env = np.ones(n, dtype=np.float32)
    h = int(hold_s * SR)
    if h < n:
        t = np.arange(n - h, dtype=np.float32) / SR
        env[h:] = np.exp(-t * 6.9 / max(rel_s, 1e-3))
    return env


def _attack(n, a_s):
    env = np.ones(n, dtype=np.float32)
    a = min(n, max(1, int(a_s * SR)))
    env[:a] = np.linspace(0, 1, a, dtype=np.float32)
    return env


def bandpass_noise(n, lo, hi, seed=None):
    rng = np.random.default_rng(seed) if seed is not None else _rng
    x = rng.standard_normal(n).astype(np.float32)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X, n).astype(np.float32)
    return y / (np.abs(y).max() + 1e-9)


def lowpass(x, cutoff):
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, n).astype(np.float32)


def karplus(f, n, decay_s=2.0, bright=0.5, seed=None):
    """Plucked string. Rendered at an integer period then resampled to the exact pitch."""
    P = max(2, int(round(SR / f)))
    f_int = SR / P
    ratio = f / f_int
    n_int = int(n * ratio) + P + 2
    rng = np.random.default_rng(seed) if seed is not None else _rng
    exc = rng.uniform(-1, 1, P).astype(np.float32)
    # soften the excitation for darker tones
    k = max(1, int((1 - bright) * 8))
    exc = np.convolve(exc, np.ones(k) / k, mode="same").astype(np.float32)
    # per-period loss so the note decays by 60 dB in decay_s
    g = 10 ** (-3 / (decay_s * f_int))
    y = np.zeros(n_int + P + 1, dtype=np.float32)
    y[1:P + 1] = exc
    pos = P + 1
    while pos < len(y):
        end = min(pos + P, len(y))
        y[pos:end] = g * 0.5 * (y[pos - P:end - P] + y[pos - P - 1:end - P - 1])
        pos = end
    y = y[1:]
    idx = np.arange(n) * ratio
    idx = idx[idx < len(y) - 1]
    return np.interp(idx, np.arange(len(y)), y).astype(np.float32)


def _wave(kind, f, t):
    ph = (f * t) % 1.0
    if kind == "square":
        return np.where(ph < 0.5, 1.0, -1.0) * 0.5
    if kind == "pulse":
        return np.where(ph < 0.125, 1.0, -1.0) * 0.5
    if kind == "triangle_wave":
        return (4 * np.abs(ph - 0.5) - 1) * 0.8
    if kind == "saw":
        return (2 * ph - 1) * 0.5
    raise KeyError(kind)


def render_pitched(kind, midi, vel, dur_s):
    f = midi_to_hz(midi)
    amp = (vel / 127) ** 0.8
    if kind == "e_piano":
        n = int((dur_s + 0.6) * SR)
        t = _t(n)
        idx = 2.5 * np.exp(-t * 3) + 0.3
        mod = np.sin(2 * np.pi * f * t) * idx
        bell = np.sin(2 * np.pi * f * 14 * t) * 0.12 * np.exp(-t * 18)
        x = np.sin(2 * np.pi * f * t + mod) * np.exp(-t * 1.2) + bell
        x *= _release_env(n, dur_s, 0.25)
        return _stereo(x * 0.5 * amp)
    if kind == "bass":
        n = int((dur_s + 0.15) * SR)
        x = karplus(f, n, decay_s=3.0, bright=0.15)
        x = lowpass(x, 900) * 1.4 + np.sin(2 * np.pi * f * _t(n)) * 0.35 * np.exp(-_t(n) * 1.5)
        x *= _release_env(n, dur_s, 0.06) * _attack(n, 0.003)
        return _stereo(x * 0.8 * amp)
    if kind == "nylon_guitar":
        n = int((dur_s + 1.2) * SR)
        x = karplus(f, n, decay_s=3.5, bright=0.55)
        x = lowpass(x, 4500)
        x *= _release_env(n, dur_s, 0.4)
        return _stereo(x * 0.7 * amp)
    if kind == "kalimba":
        n = int((dur_s + 1.5) * SR)
        t = _t(n)
        x = np.sin(2 * np.pi * f * t) * np.exp(-t * 2.5)
        x += 0.25 * np.sin(2 * np.pi * f * 6.3 * t) * np.exp(-t * 25)
        x += 0.15 * bandpass_noise(n, 1500, 5000) * np.exp(-t * 300)
        x *= _release_env(n, dur_s + 1.0, 0.3)
        return _stereo(x * 0.6 * amp)
    if kind == "music_box":
        n = int((dur_s + 2.5) * SR)
        t = _t(n)
        x = np.sin(2 * np.pi * f * t) * np.exp(-t * 1.8)
        x += 0.35 * np.sin(2 * np.pi * f * 3.0 * t) * np.exp(-t * 4)
        x += 0.15 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 9)
        x *= _attack(n, 0.002)
        return _stereo(x * 0.45 * amp)
    if kind == "pad":
        n = int((dur_s + 1.0) * SR)
        t = _t(n)
        x = sum(_wave("saw", f * d, t + o) for d, o in ((1.0, 0), (1.006, 0.13), (0.994, 0.37)))
        x = lowpass(x.astype(np.float32), min(2500, f * 6))
        x *= _attack(n, 0.35) * _release_env(n, dur_s, 0.7)
        return _stereo(x * 0.35 * amp)
    if kind in ("square", "pulse", "triangle_wave", "saw"):
        n = int((dur_s + 0.03) * SR)
        x = _wave(kind, f, _t(n)) * _attack(n, 0.002) * _release_env(n, dur_s, 0.02)
        return _stereo(x * 0.5 * amp)
    raise KeyError(kind)


def render_drum(kind, vel):
    amp = (vel / 127) ** 0.8
    if kind == "kick":
        n = int(0.45 * SR)
        t = _t(n)
        freq = 45 + 110 * np.exp(-t * 35)
        phase = 2 * np.pi * np.cumsum(freq) / SR
        x = np.sin(phase) * np.exp(-t * 7) + 0.3 * bandpass_noise(n, 1000, 6000, seed=1) * np.exp(-t * 400)
        return _stereo(x * 0.9 * amp)
    if kind == "snare":
        n = int(0.3 * SR)
        t = _t(n)
        x = 0.7 * bandpass_noise(n, 1200, 9000, seed=2) * np.exp(-t * 20)
        x += 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
        return _stereo(x * 0.7 * amp)
    if kind == "hat":
        n = int(0.08 * SR)
        t = _t(n)
        x = bandpass_noise(n, 7000, 16000, seed=3) * np.exp(-t * 70)
        return _stereo(x * 0.35 * amp)
    if kind == "open_hat":
        n = int(0.45 * SR)
        t = _t(n)
        x = bandpass_noise(n, 6500, 16000, seed=4) * np.exp(-t * 9)
        return _stereo(x * 0.3 * amp)
    if kind == "clap":
        n = int(0.3 * SR)
        t = _t(n)
        nz = bandpass_noise(n, 900, 5000, seed=5)
        env = np.exp(-t * 14) * 0.6
        for d in (0.0, 0.009, 0.018):
            env += np.where(t >= d, np.exp(-(t - d) * 180), 0)
        return _stereo(nz * env * 0.45 * amp)
    if kind == "rim":
        n = int(0.06 * SR)
        t = _t(n)
        x = np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 90) + 0.4 * bandpass_noise(n, 2000, 8000, seed=6) * np.exp(-t * 150)
        return _stereo(x * 0.5 * amp)
    if kind == "noise_hit":
        n = int(0.12 * SR)
        t = _t(n)
        step = 32
        nz = np.repeat(_rng.choice([-1.0, 1.0], n // step + 1), step)[:n]
        return _stereo(nz * np.exp(-t * 30) * 0.35 * amp)
    raise KeyError(kind)
