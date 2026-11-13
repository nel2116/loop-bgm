"""音のチェック。#75 では従来の check_loop をつなぎ目の2つのチェックに分けたもの。

しきい値は check_loop のまま（段差は |diff| の 99.9 パーセンタイルの 1.5 倍、音量差は 9 dB）。
"""

import numpy as np

from . import Issue, audio_check

SEAM_WINDOW_SECONDS = 0.25
CLICK_RATIO = 1.5
LEVEL_DB = 9


def measure_seam(x, sr):
    """つなぎ目の (段差, 普段の最大の段差, 始まりと終わりの音量差 dB)。1秒未満は None。"""
    if len(x) < sr:
        return None
    d = np.abs(np.diff(x, axis=0))
    typical = np.percentile(d, 99.9) + 1e-6
    jump = np.abs(x[0] - x[-1]).max()
    w = int(SEAM_WINDOW_SECONDS * sr)
    rms_end = np.sqrt((x[-w:] ** 2).mean()) + 1e-9
    rms_start = np.sqrt((x[:w] ** 2).mean()) + 1e-9
    db = 20 * np.log10(rms_start / rms_end)
    return jump, typical, db


def click_message(jump, typical):
    return f"つなぎ目で波形が跳んでいます（{jump:.3f}、普段の最大 {typical:.3f}）"


def level_message(db):
    return f"終わりと始まりの音量差が {db:+.1f} dB あります"


def _seam(ctx):
    if not ctx.song["loop"]:
        return None
    return measure_seam(ctx.master, ctx.sr)


def _bars(ctx):
    return tuple(sorted({1, int(ctx.song["bars"])}))


@audio_check("seam_click")
def seam_click(ctx):
    seam = _seam(ctx)
    if seam is None:
        return []
    jump, typical, _ = seam
    if jump <= typical * CLICK_RATIO:
        return []
    return [Issue("error", "seam_click", None, _bars(ctx), click_message(jump, typical),
                  "最後の小節で鳴り終わらない音（長い音符や強い余韻）を短くするか、音量を下げてください")]


@audio_check("seam_level")
def seam_level(ctx):
    seam = _seam(ctx)
    if seam is None:
        return []
    _, _, db = seam
    if abs(db) <= LEVEL_DB:
        return []
    return [Issue("warning", "seam_level", None, _bars(ctx), level_message(db),
                  "最初と最後の小節の音の数や強さをそろえてください")]
