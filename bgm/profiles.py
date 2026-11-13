"""用途 (song.json の usage) ごとのミックスと書き出しの方針。

値は docs/spec.md 5.4 の表、契約は docs/design/phase2-pipeline.md の 5 節のとおり。
#75 では方針を各段階へ渡すだけで、音には反映しない。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str                      # "video" | "game" | "trpg"
    lufs: float                    # 目標の積分ラウドネス
    voice_band: bool               # 伴奏パートの 1-4 kHz を下げるか
    loop_seconds: tuple[int, int]  # 推奨するループ長の範囲（秒）
    outputs: tuple[str, ...]       # 標準の書き出し形式


PROFILES = {
    "video": Profile("video", -16.0, True, (60, 120), ("wav", "mp3", "long")),
    "game": Profile("game", -16.0, False, (60, 180), ("ogg", "wav")),
    "trpg": Profile("trpg", -20.0, True, (120, 300), ("ogg", "mp3", "long")),
}


def validate_usage(song):
    """usage が無い、または3つの値のどれでもなければ ValueError（日本語）。"""
    if "usage" not in song:
        raise ValueError("song.json に usage がありません。用途を video（動画）/ game（ゲーム）/ "
                         "trpg（TRPGのセッション）のどれかで書いてください")
    usage = song["usage"]
    if not isinstance(usage, str) or usage not in PROFILES:
        raise ValueError(f"song.json の usage は video / game / trpg のどれかにしてください（いまは「{usage}」です）")


def resolve(song):
    validate_usage(song)
    return PROFILES[song["usage"]]
