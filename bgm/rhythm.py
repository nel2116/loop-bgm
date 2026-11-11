"""展開済み構成から固定リズムを打楽器イベントへ変換する。"""

import math
from collections.abc import Mapping

_SYNTH_VOICES = frozenset(("kick", "snare", "hat", "open_hat", "clap", "rim", "noise_hit"))
_NEW_GROOVES = ("16beat", "shuffle", "bossa", "swing_ride", "bongo_8beat")
_PATTERNS = {
    ("8beat", "4/4"): {"kick": (0, 2), "snare": (1, 3), "hat": (0, .5, 1, 1.5, 2, 2.5, 3, 3.5)},
    ("march", "4/4"): {"kick": (0, 2), "snare": (1, 3)},
    ("march", "6/8"): {"kick": (0,), "snare": (1.5,)},
    ("waltz", "3/4"): {"kick": (0,), "snare": (1, 2), "hat": (0, 1, 2)},
    ("16beat", "4/4"): {"kick": (0, 2), "snare": (1, 3), "hat": tuple(i / 4 for i in range(16))},
    ("shuffle", "4/4"): {"kick": (0, 2), "snare": (1, 3),
                           "hat": (0, 2/3, 1, 1+2/3, 2, 2+2/3, 3, 3+2/3)},
    ("bossa", "4/4"): {"kick": (0, 1.5, 2, 3.5), "rim": (0, 1.5, 3),
                         "hat": (0, .5, 1, 1.5, 2, 2.5, 3, 3.5)},
    ("swing_ride", "4/4"): {"kick": (0, 2), "snare": (1, 3), "ride": (0, 1, 1+2/3, 2, 3, 3+2/3)},
    ("bongo_8beat", "4/4"): {"bongo_hi": (0, .5, 1.5, 2, 2.5, 3.5), "bongo_lo": (1, 3),
                               "tambourine": (0, .5, 1, 1.5, 2, 2.5, 3, 3.5)},
}


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def compile_rhythm(part, song, occurrences, *, available_voices=None):
    """音源に触れず (四分音符単位の拍, 既存voice名, velocity) を返す。

    kitは使用可能なvoice名の一覧、voicesは従来の個別設定であり、
    どちらも打楽器名の置換には使わない。既定はサンプル不要の合成音。
    """
    name = part.get("name", "rhythm") if isinstance(part, dict) else "rhythm"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/songはオブジェクトで指定してください")
    groove = part.get("groove")
    if groove not in ("8beat", "march", "waltz", "ambient_none", *_NEW_GROOVES):
        raise error("grooveは8beat/16beat/shuffle/bossa/march/waltz/swing_ride/bongo_8beat/ambient_noneから指定してください")
    if part.get("role", "rhythm") != "rhythm" or part.get("type", "drums") != "drums":
        raise error("リズム伴奏はrole=rhythm、type=drumsで指定してください")
    if any(field in part for field in ("bars", "phrases", "grid", "style")):
        raise error("grooveとbars/phrases/grid/styleは併用できません（空の指定も含む）")
    meter = song.get("meter")
    if meter not in ("4/4", "3/4", "6/8"):
        raise error("meterは4/4、3/4、6/8から指定してください")
    bar_beats = 4 if meter == "4/4" else 3
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrencesは空でないリストで指定してください")
    end, next_bar = 0, 1
    for occ in occurrences:
        if (not isinstance(occ, dict) or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or type(occ.get("bars")) is not int or occ["bars"] < 1
                or not _number(occ.get("start_beat")) or occ["start_beat"] != end):
            raise error("occurrencesの名前・素材・小節・開始位置が不正です", next_bar)
        end += occ["bars"] * bar_beats
        next_bar += occ["bars"]
    selected = part.get("sections")
    names = {occ["name"] for occ in occurrences}
    if "sections" in part and (not isinstance(selected, list)
                              or any(not isinstance(s, str) or s not in names for s in selected)):
        raise error("sectionsは展開されたセクション名のリストで指定してください")
    first_bar = next((o["start_bar"] for o in occurrences if selected is None or o["name"] in selected), 1)
    if groove != "ambient_none" and (groove, meter) not in _PATTERNS:
        raise error(f"groove={groove}は拍子{meter}に対応していません", first_bar)
    pattern = {} if groove == "ambient_none" else _PATTERNS[groove, meter]
    swing, unit = song.get("swing", 0), song.get("swing_unit", .5)
    if groove in _NEW_GROOVES:
        if not _number(swing) or not _number(unit) or unit <= 0:
            raise error("song.swingは有限数、song.swing_unitは正の有限数で指定してください", first_bar)
        if groove in ("shuffle", "swing_ride") and swing != 0:
            raise error(f"groove={groove}とsong.swing非0は併用できません（song.swing_unitによる二重適用防止）", first_bar)
    velocity = part.get("velocity", 95)
    if not _number(velocity) or not 1 <= velocity <= 127:
        raise error("velocityは1〜127の有限数で指定してください", first_bar)
    if available_voices is None:
        available = _SYNTH_VOICES
    else:
        if (not isinstance(available_voices, (Mapping, list, tuple, set, frozenset))
                or any(not isinstance(v, str) or not v for v in available_voices)):
            raise error("available_voicesは空でない打楽器名の集合で指定してください", first_bar)
        available = set(available_voices)
    kit = part.get("kit")
    if "kit" in part:
        if not isinstance(kit, list) or any(not isinstance(v, str) or v not in available for v in kit):
            raise error("kitは使用可能な打楽器名の配列で指定してください", first_bar)
        if any(v not in kit for v in pattern):
            raise error("kitにgrooveで必要な打楽器名がありません", first_bar)
    voices = part.get("voices", {})
    if not isinstance(voices, dict):
        raise error("voicesは打楽器名と設定のオブジェクトで指定してください", first_bar)
    for voice, config in voices.items():
        if not isinstance(voice, str) or voice not in available:
            raise error(f"voicesの打楽器名{voice!r}はありません", first_bar)
        if config is None:
            continue
        if not isinstance(config, dict):
            raise error(f"voices.{voice}は設定のオブジェクトまたはnullで指定してください", first_bar)
        for field in ("pan", "volume"):
            if field in config and (not _number(config[field]) or abs(config[field]) > 3.4028234663852886e38):
                raise error(f"voices.{voice}.{field}は有限数で指定してください", first_bar)
    if any(v not in available for v in pattern):
        raise error("grooveで必要な打楽器名がavailable_voicesにありません", first_bar)
    strong = (0, 2) if meter == "4/4" else (0, 1.5) if meter == "6/8" else (0,)
    events = []
    for occ in occurrences:
        chosen = selected is None or occ["name"] in selected
        if not chosen and groove not in _NEW_GROOVES:
            continue
        for index in range(occ["bars"]):
            start = occ["start_beat"] + index * bar_beats
            for voice, offsets in pattern.items():
                for offset in offsets:
                    beat = start + offset
                    if groove in _NEW_GROOVES and swing:
                        # renderer._swingと同じ絶対拍の式で検証し、適用はrendererに一度だけ任せる。
                        try:
                            q = beat / unit
                            moved = beat
                            if abs(q - round(q)) < 1e-6 and int(round(q)) % 2 == 1:
                                moved = beat + swing * unit / 3
                            valid = math.isfinite(moved) and start <= moved < start + bar_beats
                        except (OverflowError, ValueError):
                            valid = False
                        if not valid:
                            raise error("song.swing / song.swing_unitによる打点が元の小節外または非有限になります",
                                        occ["start_bar"] + index)
                    factor = (0.8 if voice in ("hat", "ride", "tambourine") else 1) * (1.2 if offset in strong else 1)
                    if chosen:
                        events.append((beat, voice, max(1, min(127, round(velocity * factor)))))
    # 同時刻は従来の小節内voice順を維持する。
    return sorted(events, key=lambda event: event[0])
