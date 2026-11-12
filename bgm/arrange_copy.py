"""描画前の有音程イベントをコピーし、参照を依存順に解決する。"""

import math
from collections.abc import Mapping


def _error(part, message, bar=1):
    name = part.get("name", "arrange") if isinstance(part, Mapping) else "arrange"
    return ValueError(f"[{name}] {bar}番目の小節: {message}")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _copy_fields(part):
    if not isinstance(part, Mapping):
        raise _error(part, "part はオブジェクトで指定してください")
    if part.get("role") != "arrange" or part.get("type", "notes") != "notes":
        raise _error(part, "copy は role=arrange、type=notes で指定してください")
    if not isinstance(part.get("copy"), str) or not part["copy"].strip():
        raise _error(part, "copy は参照元の空でないパート名で指定してください")
    if any(field in part for field in ("bars", "phrases", "grid", "style", "groove", "accent", "source", "velocity", "kit", "voices")):
        raise _error(part, "copy と bars/phrases/grid/style/groove/accent/source/velocity/kit/voices は併用できません")
    if "instrument" in part and (not isinstance(part["instrument"], str) or not part["instrument"].strip()):
        raise _error(part, "instrument は空でない楽器名で指定してください")


def _pitched(part):
    return (part.get("role") in (None, "melody", "bass", "chords", "arrange")
            and ("role" not in part or part["role"] is not None)
            and part.get("type", "notes") == "notes"
            and "groove" not in part and part.get("accent") != "offbeat_tick")


def reference_order(parts, *, reference_fields=("copy",)):
    """全パート名を依存先優先で返す。source は counter の直接メロディ参照だけ。"""
    if (not isinstance(reference_fields, (tuple, list))
            or any(field not in ("copy", "source") for field in reference_fields)):
        raise _error({}, "reference_fields は copy/source の一覧で指定してください")
    if not isinstance(parts, list):
        raise _error({}, "parts は一覧で指定してください")
    named = {}
    for part in parts:
        if not isinstance(part, Mapping):
            raise _error(part, "parts の各要素はオブジェクトで指定してください")
        name = part.get("name")
        if not isinstance(name, str) or not name.strip() or name in named:
            raise _error(part, "name は重複のない空でないパート名で指定してください")
        named[name] = part
    edges = {}
    for name, part in named.items():
        if "copy" in part:
            _copy_fields(part)
        if "source" in part or part.get("accent") == "counter":
            if (part.get("role") != "arrange" or part.get("type", "notes") != "notes"
                    or part.get("accent") != "counter"
                    or any(field in part for field in ("copy", "bars", "phrases", "grid", "style", "groove", "kit", "voices"))):
                raise _error(part, "source は role=arrange、type=notes、accent=counter 専用です")
            if not isinstance(part.get("source"), str) or not part["source"].strip():
                raise _error(part, "counter の source は空でないパート名で指定してください")
        edges[name] = []
        for field in reference_fields:
            if field not in part:
                continue
            target = part[field]
            if target not in named:
                raise _error(part, f"{field} の参照元 {target!r} がありません")
            if target == name:
                raise _error(part, f"{field} で自分自身を参照できません")
            source = named[target]
            if not _pitched(source):
                raise _error(part, f"{field} の参照元は有音程パートで指定してください")
            if field == "source" and (source.get("role") != "melody"
                                      or any(key in source for key in ("copy", "accent", "style", "groove"))
                                      or not ("bars" in source or "phrases" in source)):
                raise _error(part, "counter の参照元は直接記述した role=melody にしてください")
            edges[name].append(target)
    result, state = [], {}
    # 深いコピー連鎖でも Python の再帰上限に依存しない。
    for name in named:
        stack = [(name, False)]
        while stack:
            current, exiting = stack.pop()
            if exiting:
                state[current] = 2
                result.append(current)
            elif state.get(current) == 1:
                raise _error(named[current], "パート参照が循環しています")
            elif state.get(current) != 2:
                state[current] = 1
                stack.append((current, True))
                stack.extend((target, False) for target in reversed(edges[current]))
    return result


def resolve_copy_instrument(part, effective_instruments):
    """楽器だけを継承する。楽器カタログの検証は呼出側で行う。"""
    _copy_fields(part)
    if not isinstance(effective_instruments, Mapping):
        raise _error(part, "effective_instruments は解決済み楽器のオブジェクトで指定してください")
    instrument = part["instrument"] if "instrument" in part else effective_instruments.get(part["copy"])
    if not isinstance(instrument, str) or not instrument.strip():
        raise _error(part, "参照元の instrument が未解決です")
    return instrument


def compile_copy(part, song, occurrences, source_events, *, note_range=(0, 127)):
    """元の音高変換済み・DSP前イベントに相対音高変換だけを適用する。

    元の選択済みイベントを入力とし、開始拍が選択出現内にある音だけを残す。
    和声で再分割しない。元の生成音の hard window と描画時の gate 等は
    呼出側が別 metadata で保持し、コピー先の設定を一度だけ適用する。
    """
    _copy_fields(part)
    if not isinstance(song, Mapping):
        raise _error(part, "song はオブジェクトで指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in ("4/4", "3/4", "6/8"):
        raise _error(part, "meter は 4/4、3/4、6/8 に対応しています")
    beats = 4 if meter == "4/4" else 3
    octave, transpose = part.get("octave", 0), part.get("transpose", 0)
    if type(octave) is not int or type(transpose) is not int:
        raise _error(part, "octave/transpose は整数で指定してください")
    if (not isinstance(note_range, (tuple, list)) or len(note_range) != 2
            or any(type(p) is not int for p in note_range) or not 0 <= note_range[0] <= note_range[1] <= 127):
        raise _error(part, "note_range は0〜127の整数の下限・上限で指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise _error(part, "occurrences は空でない一覧で指定してください")
    end = 0
    for occ in occurrences:
        if not isinstance(occ, Mapping):
            raise _error(part, "出現はオブジェクトで指定してください")
        start, bars, bar = occ.get("start_beat"), occ.get("bars"), occ.get("start_bar")
        if (not _finite(start) or start < end or type(bars) is not int or bars <= 0
                or type(bar) is not int or bar < 1
                or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))):
            raise _error(part, "出現の名前・開始拍・小節数・全体小節番号が不正です")
        if not _finite(bars * beats) or not _finite(start + bars * beats):
            raise _error(part, "出現の終端は有限数で指定してください", bar)
        end = start + bars * beats
    selected = part.get("sections")
    if "sections" in part and (not isinstance(selected, list)
                               or any(not isinstance(s, str) or s not in {o["name"] for o in occurrences} for s in selected)):
        raise _error(part, "sections は展開された出現名の一覧で指定してください")
    if not isinstance(source_events, list):
        raise _error(part, "source_events はイベントの一覧で指定してください")
    result = []
    previous = -1
    for event in source_events:
        if not isinstance(event, (tuple, list)) or len(event) != 4:
            raise _error(part, "元イベントは (拍, MIDI一覧, 長さ, 強さ) で指定してください")
        beat, pitches, duration, velocity = event
        occ = next((o for o in occurrences if _finite(beat)
                    and o["start_beat"] <= beat < o["start_beat"] + o["bars"] * beats), None)
        bar = occ["start_bar"] + int((beat - occ["start_beat"]) // beats) if occ is not None else 1
        if (not _finite(beat) or beat < 0 or beat < previous or not _finite(duration) or duration <= 0
                or not _finite(beat + duration) or not _finite(velocity) or not 1 <= velocity <= 127
                or not isinstance(pitches, list) or not pitches
                or any(type(p) is not int or not 0 <= p <= 127 for p in pitches)):
            raise _error(part, "元イベントの拍・音高・長さ・強さが不正です", bar)
        previous = beat
        if occ is None:
            raise _error(part, "元イベントの開始拍が曲の出現区間外です")
        tones = [p + octave * 12 + transpose for p in pitches]
        low, high = note_range
        minimum = -((min(tones) - low) // 12)
        maximum = (high - max(tones)) // 12
        if minimum > maximum:
            raise _error(part, "全構成音の音程と順序を保って音域に収められません", bar)
        shift = min(max(0, minimum), maximum) * 12
        if selected is None or occ["name"] in selected:
            result.append((beat, [p + shift for p in tones], min(duration, occ["start_beat"] + occ["bars"] * beats - beat), velocity))
    return result
