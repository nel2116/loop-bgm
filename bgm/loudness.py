"""ITU-R BS.1770-4 の積分ラウドネス (LUFS) とサンプルピーク。numpy だけで測る。

契約は docs/design/phase2-pipeline.md の 6 節。
"""

import math

import numpy as np

from .paths import SR

BLOCK_SECONDS = 0.4
STEP_SECONDS = 0.1  # 75% 重なり
ABSOLUTE_GATE = -70.0
RELATIVE_GATE = -10.0


def _biquads(sr):
    """K特性の2段のバイクアッド (b, a)。libebur128 と同じアナログ原型から任意の標本化周波数で作る。"""
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10 ** (gain_db / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = ([(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0],
             [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0])
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    a0 = 1 + k / q + k * k
    highpass = ([1.0, -2.0, 1.0], [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0])
    return shelf, highpass


def k_weight(x, sr=SR):
    """K特性を掛けた信号を返す。形は入力と同じ (n,) または (n, ch)。

    巡回畳み込みにならないよう 1 秒以上ゼロを詰めて FFT し、バイクアッドの厳密な周波数応答を掛ける。
    フィルターの余韻はゼロ詰めの範囲で十分に減衰する。
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n == 0:
        return x.copy()
    size = 1 << (n + sr - 1).bit_length()
    w = 2 * np.pi * np.fft.rfftfreq(size)
    z = np.exp(-1j * w)
    h = np.ones_like(z)
    for b, a in _biquads(sr):
        h *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    spec = np.fft.rfft(x, size, axis=0)
    spec *= h if x.ndim == 1 else h[:, None]
    return np.fft.irfft(spec, size, axis=0)[:n]


def integrated_lufs(x, sr=SR):
    """積分ラウドネス (LUFS)。1ブロック (400ms) に満たない入力や無音は -inf。"""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    block, step = int(round(BLOCK_SECONDS * sr)), int(round(STEP_SECONDS * sr))
    if len(x) < block:
        return float("-inf")
    y = k_weight(x, sr)
    power = np.concatenate([np.zeros((1, y.shape[1])), np.cumsum(y * y, axis=0)])
    starts = np.arange(0, len(y) - block + 1, step)
    z = ((power[starts + block] - power[starts]) / block).sum(axis=1)  # チャンネルの重みはすべて 1.0
    with np.errstate(divide="ignore"):
        loud = -0.691 + 10 * np.log10(z)
    gated = z[loud > ABSOLUTE_GATE]
    if len(gated) == 0:
        return float("-inf")
    relative = -0.691 + 10 * math.log10(gated.mean()) + RELATIVE_GATE
    gated = z[(loud > ABSOLUTE_GATE) & (loud > relative)]
    return float(-0.691 + 10 * math.log10(gated.mean()))


def sample_peak_db(x):
    """サンプルの絶対値の最大 (dBFS)。無音や空の入力は -inf。"""
    x = np.asarray(x, dtype=np.float64)
    peak = float(np.abs(x).max()) if x.size else 0.0
    return 20 * math.log10(peak) if peak > 0 else float("-inf")
