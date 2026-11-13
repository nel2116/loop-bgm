"""承認済みの句頭装飾と裏拍打楽器を純粋なイベントへ変換する。"""

import math
from collections.abc import Mapping

_METERS = {"4/4": (4, (.5, 1.5, 2.5, 3.5)), "3/4": (3, (.5, 1.5, 2.5)), "6/8": (3, (.75, 2.25))}
_SYNTH_VOICES = frozenset(("kick", "snare", "hat", "open_hat", "clap", "rim", "noise_hit"))


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _before(left, right):
    # 同じ有理数境界の乗算と加算の丸め差だけを許容する。
    return left < right and right - left > 4 * max(math.ulp(left), math.ulp(right))


def _settings(part, song, occurrences, accent):
    name = part.get("name", "arrange") if isinstance(part, dict) else "arrange"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/songはオブジェクトで指定してください")
    drum = accent == "offbeat_tick"
    if part.get("role") != "arrange" or part.get("type", "drums" if drum else "notes") != ("drums" if drum else "notes"):
        raise error("role=arrangeと装飾に対応するtypeを指定してください")
    if part.get("accent") != accent:
        raise error(f"accent={accent}を指定してください")
    if any(field in part for field in ("bars", "phrases", "grid", "style", "groove", "copy", "source")):
        raise error("accentとbars/phrases/grid/style/groove/copy/sourceは併用できません（空の指定も含む）")
    if any(field in part for field in (("instrument",) if drum else ("kit", "voices"))):
        raise error("装飾の種類とinstrument/kit/voicesの指定が一致しません")
    if not drum and (not isinstance(part.get("instrument"), str) or not part["instrument"]):
        raise error("instrumentは空でない楽器名で指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in _METERS:
        raise error("meterは4/4、3/4、6/8から指定してください")
    beats, offsets = _METERS[meter]
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrencesは空でないリストで指定してください")
    end, next_bar = 0, 1
    for occ in occurrences:
        if (not isinstance(occ, dict) or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or type(occ.get("bars")) is not int or occ["bars"] < 1
                or not _finite(occ.get("start_beat")) or occ["start_beat"] != end
                or not _finite(occ["bars"] * beats + end)):
            raise error("occurrencesの名前・素材・小節・開始位置が不正です", next_bar)
        end += occ["bars"] * beats
        next_bar += occ["bars"]
    selected = part.get("sections")
    if "sections" in part and (not isinstance(selected, list)
                              or any(not isinstance(s, str) or s not in {o["name"] for o in occurrences} for s in selected)):
        raise error("sectionsは展開されたセクション名のリストで指定してください")
    chosen = [o for o in occurrences if selected is None or o["name"] in selected]
    first_bar = chosen[0]["start_bar"] if chosen else 1
    velocity = part.get("velocity", 95 if drum else 90)
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise error("velocityは1〜127の有限数で指定してください", first_bar)
    return error, beats, offsets, chosen, end, velocity


def compile_phrase_start(part, song, occurrences, harmony, *, note_range=(0, 127), pitch_resolver=None):
    """各選択出現の頭だけに、実和声の最高音の1オクターブ上を置く。

    gateやswing等は適用しない。描画側は和声・出現・曲末の窓を保持する。
    """
    error, beats, _, chosen, song_end, velocity = _settings(part, song, occurrences, "phrase_start")
    octave, transpose = part.get("octave", 0), part.get("transpose", 0)
    if type(octave) is not int or type(transpose) is not int:
        raise error("octave/transposeは整数で指定してください")
    if (not isinstance(note_range, (tuple, list)) or len(note_range) != 2
            or any(type(p) is not int for p in note_range) or not 0 <= note_range[0] <= note_range[1] <= 127):
        raise error("note_rangeは0〜127の整数の下限・上限で指定してください")
    if not isinstance(harmony, list):
        raise error("harmonyはリストで指定してください")
    previous_end, previous_beat = 0, -1
    for chord in harmony:
        if not isinstance(chord, dict):
            raise error("harmonyの各要素はオブジェクトで指定してください")
        bar, beat, duration = (chord.get(k) for k in ("bar", "beat", "duration"))
        if type(bar) is not int or bar < 1:
            raise error("和声のbarは正の整数で指定してください")
        if (not _finite(beat) or beat < 0 or beat <= previous_beat or _before(beat, previous_end) or not _finite(duration)
                or duration <= 0 or not _finite(beat + duration)):
            raise error("和声のbeat/durationは重ならない有限の正の区間で指定してください", bar)
        occ = next((o for o in occurrences if o["start_beat"] <= beat < o["start_beat"] + o["bars"] * beats), None)
        if (occ is None or chord.get("section") != occ["name"] or chord.get("source") != occ["source"]
                or bar != occ["start_bar"] + math.floor((beat - occ["start_beat"]) / beats)
                or _before(occ["start_beat"] + occ["bars"] * beats, beat + duration)):
            raise error("和声のsection/source/barと区間が出現構造に一致しません", bar)
        pitches = chord.get("pitches")
        if not isinstance(pitches, list) or not pitches or any(type(p) is not int or not 0 <= p <= 127 for p in pitches):
            raise error("和声のpitchesはMIDI整数の空でない一覧で指定してください", bar)
        previous_end = beat + duration
        previous_beat = beat
    events = []
    for occ in chosen:
        start = occ["start_beat"]
        chord = next((c for c in harmony if c["section"] == occ["name"] and c["source"] == occ["source"]
                      and c["bar"] == occ["start_bar"] and c["beat"] <= start < c["beat"] + c["duration"]), None)
        if chord is None:
            raise error("句頭を覆う和声がありません", occ["start_bar"])
        pitch = max(chord["pitches"]) + 12 + octave * 12 + transpose
        low, high = note_range
        minimum, maximum = -((pitch - low) // 12), (high - pitch) // 12
        if pitch_resolver is None and minimum > maximum:
            raise error("音程クラスを保ったまま音域に収められません", occ["start_bar"])
        pitch += min(max(0, minimum), maximum) * 12
        duration = min(.5, chord["beat"] + chord["duration"] - start, occ["bars"] * beats, song_end - start)
        if duration > 0:
            if pitch_resolver is not None:
                pitch = pitch_resolver(start, [max(chord["pitches"]) + 12], occ["start_bar"])[0]
            events.append((start, [pitch], duration, max(1, min(127, round(velocity * 1.2)))))
    return events


def compile_offbeat_tick(part, song, occurrences, *, available_voices=None):
    """既存hatだけを使い、小節ごとの裏拍をdrum3要素タプルへ変換する。"""
    error, beats, offsets, chosen, _, velocity = _settings(part, song, occurrences, "offbeat_tick")
    available = _SYNTH_VOICES if available_voices is None else available_voices
    if (not isinstance(available, (Mapping, list, tuple, set, frozenset))
            or any(not isinstance(v, str) or not v for v in available)):
        raise error("available_voicesは使用可能な打楽器名の集合で指定してください")
    if "hat" not in available:
        raise error("available_voicesにhatがありません")
    if "kit" in part:
        kit = part["kit"]
        if not isinstance(kit, list) or any(not isinstance(v, str) or v not in available for v in kit) or "hat" not in kit:
            raise error("kitはhatを含む使用可能な打楽器名の配列で指定してください")
    voices = part.get("voices", {})
    if not isinstance(voices, dict):
        raise error("voicesは打楽器名と設定のオブジェクトで指定してください")
    for voice, config in voices.items():
        if not isinstance(voice, str) or voice not in available:
            raise error("voicesに使用できない打楽器名があります")
        if config is None:
            continue
        if not isinstance(config, dict):
            raise error("voicesの各値は設定オブジェクトまたはnullで指定してください")
        for field in ("volume", "pan"):
            if field in config and (not _finite(config[field]) or abs(config[field]) > 3.4028234663852886e38):
                raise error(f"voices.{voice}.{field}は有限数で指定してください")
    swing, unit = song.get("swing", 0), song.get("swing_unit", .5)
    if not _finite(swing) or not _finite(unit) or unit <= 0:
        raise error("song.swingは有限数、song.swing_unitは正の有限数で指定してください")
    events = []
    for occ in occurrences:
        for index in range(occ["bars"]):
            start = occ["start_beat"] + index * beats
            for offset in offsets:
                beat = start + offset
                try:
                    moved = beat
                    if swing:
                        q = beat / unit
                        if abs(q - round(q)) < 1e-6 and int(round(q)) % 2 == 1:
                            moved += swing * unit / 3
                    valid = math.isfinite(moved) and beat <= moved < start + beats
                except (OverflowError, ValueError):
                    valid = False
                if not valid:
                    raise error("song.swing / song.swing_unitによる打点が負方向・小節外・非有限になります", occ["start_bar"] + index)
                if occ in chosen:
                    events.append((beat, "hat", max(1, min(127, round(velocity * .8)))))
    return events
