"""check 段階: 自動チェックの登録と実行。

契約は docs/design/phase2-pipeline.md の 4 節（#75 以降は固定）。音符のチェックは checks/notes.py、
音のチェックは checks/audio.py に書き、それぞれ @note_check / @audio_check で登録する。
"""

from dataclasses import dataclass

import numpy as np

from ..profiles import Profile

LEVELS = ("error", "warning")


@dataclass(frozen=True)
class Issue:
    level: str               # "error" | "warning"
    check: str
    part: str | None
    bars: tuple[int, ...]
    message: str
    hint: str | None


@dataclass(frozen=True)
class CheckContext:
    song: dict               # load_song の結果
    profile: Profile
    notes: dict              # build/notes.json の文書
    stems: dict              # パート名 -> float32 (n, 2)。折り返し後、音量・定位の前
    master: np.ndarray       # float32 (n, 2)。write 段階に渡したもの
    sr: int


_NOTE_CHECKS = []
_AUDIO_CHECKS = []


def _register(registry, check_id):
    def decorator(fn):
        if any(cid == check_id for cid, _ in _NOTE_CHECKS + _AUDIO_CHECKS):
            raise ValueError(f"check id {check_id} is registered twice")
        registry.append((check_id, fn))
        return fn
    return decorator


def note_check(check_id):
    """音符だけを読むチェック: fn(ctx) -> Iterable[Issue]。"""
    return _register(_NOTE_CHECKS, check_id)


def audio_check(check_id):
    """音を読むチェック: fn(ctx) -> Iterable[Issue]。"""
    return _register(_AUDIO_CHECKS, check_id)


def registered():
    """登録順のチェック id（音符のチェック、音のチェックの順）。"""
    return [cid for cid, _ in _NOTE_CHECKS + _AUDIO_CHECKS]


def run_checks(ctx):
    issues = []
    for check_id, fn in _NOTE_CHECKS + _AUDIO_CHECKS:
        for issue in fn(ctx):
            if issue.level not in LEVELS:
                raise ValueError(f"{check_id}: unknown level {issue.level!r}")
            issues.append(issue)
    return issues


from . import audio, notes  # noqa: E402,F401  登録のために一度だけ読み込む
