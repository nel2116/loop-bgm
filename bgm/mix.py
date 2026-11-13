"""mix / master 段階: パートを混ぜ、仕上げの音量をそろえる。

#75 では従来の render_song の処理をそのまま移しただけで、音は変わらない（profile はまだ使わない）。
docs/design/phase2-pipeline.md の 1 節。
"""

import numpy as np

from .paths import SR
from .render import pan_gains


def mix_stems(song, stems, profile):
    """volume / pan / mute / solo を反映して混ぜた float32 (n, 2) を返す。"""
    n = max(len(a) for a in stems.values())
    mix = np.zeros((n, 2), np.float32)
    solo = [p for p in song["parts"] if p.get("solo")]
    for part in song["parts"]:
        if part.get("mute") or (solo and not part.get("solo")):
            continue
        a = stems[part["name"]]
        gl, gr = pan_gains(part.get("pan", 0))
        mix[:len(a)] += a * (np.array([gl, gr], np.float32) * np.float32(part.get("volume", 0.8)))
    return mix


def finish(song, mixed, profile):
    """ピークを -1 dBFS（と master.gain_db の減衰）にそろえ、ループしない曲は終わりをフェードする。"""
    mix = mixed
    peak = np.abs(mix).max()
    target = 10 ** (-1 / 20) * 10 ** (min(0, song["master"]["gain_db"]) / 20)
    gain = target / peak if peak > 0 else 1.0
    mix *= np.float32(gain)
    if not song["loop"]:
        fade = min(len(mix), int(0.05 * SR))
        mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return mix, {"gain": float(gain)}
