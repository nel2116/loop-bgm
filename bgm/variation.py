"""変化の区間計画と純粋な音高・休止処理。描画への接続は呼出側が担当する。"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .arrange_copy import reference_order
from .rhythm import compile_rhythm


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    start_bar: int
    occurrence: int
    name: str


@dataclass(frozen=True)
class Rule:
    part: str
    action: str
    intervals: tuple[Interval, ...]
    instrument: str | None = None
    every: int | None = None
    beats: float | None = None


@dataclass(frozen=True)
class VariationPlan:
    rules: tuple[Rule, ...]
    beats_per_bar: float


@dataclass(frozen=True)
class InstrumentSpan:
    part: str
    start: float
    end: float
    instrument: str
    note_range: tuple[int, int]


@dataclass(frozen=True)
class RestResult:
    events: list
    indices: tuple[int, ...]
    windows: tuple[tuple[float, float] | None, ...]


def _error(name, message, bar=1):
    return ValueError(f"[{name}] {bar}番目の小節: {message}")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _range(value, name, bar=1):
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or any(type(p) is not int for p in value) or not 0 <= value[0] <= value[1] <= 127):
        raise _error(name, "音域は0〜127の整数の下限・上限で指定してください", bar)
    return tuple(value)


def _catalog(pitched_catalog):
    if not isinstance(pitched_catalog, Mapping):
        raise _error("variation", "pitched_catalogは楽器名と音域のオブジェクトで指定してください")
    result = {}
    for name, bounds in pitched_catalog.items():
        if not isinstance(name, str) or not name:
            raise _error("variation", "楽器名は空でない文字列で指定してください")
        result[name] = _range(bounds, "variation")
    return result


def _occurrences(occurrences, beats):
    if not isinstance(occurrences, (list, tuple)) or not occurrences:
        raise _error("variation", "occurrencesは空でない出現一覧で指定してください")
    end, next_bar = 0, 1
    for index, occ in enumerate(occurrences):
        if (not isinstance(occ, Mapping) or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("bars")) is not int or occ["bars"] <= 0
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or type(occ.get("occurrence")) is not int or occ["occurrence"] != index
                or not _finite(occ.get("start_beat")) or occ["start_beat"] != end):
            raise _error("variation", "出現の名前・素材・開始位置・小節数が不正です", next_bar)
        try:
            stop = end + occ["bars"] * beats
        except OverflowError as exc:
            raise _error("variation", "出現の終端を有限数で計算できません", next_bar) from exc
        if not _finite(stop) or stop <= end:
            raise _error("variation", "出現の終端を有限の正幅で計算できません", next_bar)
        end, next_bar = stop, next_bar + occ["bars"]


def _selection(part, occurrences):
    names = {o["name"] for o in occurrences}
    selected = part.get("sections", list(names))
    if (not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected)
            or len(set(selected)) != len(selected)):
        raise _error(part["name"], "sectionsは重複のない出現名の配列で指定してください")
    return selected


def _drums(part):
    return part.get("type") == "drums" or "groove" in part or part.get("accent") == "offbeat_tick"


def _interval(occ, beats):
    return Interval(occ["start_beat"], occ["start_beat"] + occ["bars"] * beats,
                    occ["start_bar"], occ["occurrence"], occ["name"])


def _fill_settings(part, song, occurrences, available, bar):
    name = part["name"]
    groove = part.get("groove")
    if not _drums(part) or part.get("accent") == "offbeat_tick":
        raise _error(name, "fill_last_barは直接記述ドラムまたはgroove専用です", bar)
    if any(field in part for field in ("accent", "copy", "source", "style", "phrases", "grid")):
        raise _error(name, "fill_last_barは装飾・コピー・有音程記譜と併用できません", bar)
    if "groove" in part:
        # 既存の拍子表・kit・swing検証を使い、無選択でも未対応設定を隠さない。
        compile_rhythm(part, song, list(occurrences), available_voices=available)
    if groove in ("shuffle", "swing_ride") and song.get("swing", 0) != 0:
        raise _error(name, "shuffle/swing_rideとsong.swing非0は併用できません", bar)
    for field, default in (("swing", 0), ("swing_unit", .5)):
        value = song.get(field, default)
        if not _finite(value) or field == "swing_unit" and value <= 0:
            raise _error(name, "swingは有限数、swing_unitは正の有限数で指定してください", bar)
    kit = part.get("kit")
    if "kit" in part and (not isinstance(kit, list) or any(not isinstance(v, str) or v not in available for v in kit)):
        raise _error(name, "kitは実在する打楽器名の配列で指定してください", bar)
    bongo = groove == "bongo_8beat" or (kit is not None and {"bongo_lo", "bongo_hi"} <= set(kit)
                                        and not {"kick", "snare"} & set(kit))
    required = {"bongo_lo", "bongo_hi"} if bongo else {"kick", "snare"}
    if not required <= available or kit is not None and not required <= set(kit):
        raise _error(name, "fillで必要な実在の打楽器名がavailable_voices/kitにありません", bar)
    velocity = part.get("velocity", 95)
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise _error(name, "velocityは1〜127の有限数で指定してください", bar)
    voices = part.get("voices", {})
    if not isinstance(voices, Mapping):
        raise _error(name, "voicesは打楽器名と設定のオブジェクトで指定してください", bar)
    for voice, settings in voices.items():
        if not isinstance(voice, str) or voice not in available or settings is not None and not isinstance(settings, Mapping):
            raise _error(name, "voicesの打楽器名・設定が不正です", bar)
        for field in ("volume", "pan"):
            if (settings is not None and field in settings
                    and (not _finite(settings[field]) or abs(settings[field]) > 3.4028234663852886e38)):
                raise _error(name, "voicesのvolume/panは有限数で指定してください", bar)


def compile_variation(song, occurrences, *, pitched_catalog, available_voices):
    """承認済み五動作の構文・対象・競合を検証し、順序非依存の区間計画を返す。

    有効な空選択も全設定を検証する。既存記譜の詳細検証は各compilerが担当する。
    fill/periodの生成器には依存せず、呼出側がrulesの値を各APIに渡す。
    """
    if not isinstance(song, Mapping):
        raise _error("variation", "songはオブジェクトで指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in ("4/4", "3/4", "6/8"):
        raise _error("variation", "meterは4/4、3/4、6/8で指定してください")
    beats = 4 if meter == "4/4" else 3
    _occurrences(occurrences, beats)
    catalog = _catalog(pitched_catalog)
    if (not isinstance(available_voices, (set, frozenset, tuple, list, Mapping))
            or any(not isinstance(v, str) or not v for v in available_voices)):
        raise _error("variation", "available_voicesは実在する打楽器名の集合で指定してください")
    available = set(available_voices)
    parts = song.get("parts")
    reference_order(parts, reference_fields=("copy", "source"))
    named = {p["name"]: p for p in parts}
    for name, part in named.items():
        if ("role" in part and part["role"] not in ("melody", "bass", "chords", "rhythm", "arrange")
                or "type" in part and part["type"] not in ("notes", "drums")):
            raise _error(name, "role/typeの指定が不正です")
        if (_drums(part) and part.get("role") not in (None, "rhythm", "arrange")
                or not _drums(part) and part.get("role") == "rhythm"):
            raise _error(name, "role/typeと有音程・打楽器の指定が競合しています")
        if (("style" in part or "groove" in part)
                and any(field in part for field in ("bars", "phrases", "grid", "copy", "accent", "source"))
                or "style" in part and "groove" in part
                or ("phrases" in part or "grid" in part) and ("bars" in part or _drums(part))):
            raise _error(name, "生成・記譜の項目を併用できません（空やnullも含む）")
        if not _drums(part):
            for field in ("octave", "transpose"):
                if type(part.get(field, 0)) is not int:
                    raise _error(name, "octave/transposeは整数で指定してください")
            for field in ("gate", "strum"):
                if field in part and not _finite(part[field]):
                    raise _error(name, "gate/strumは有限数で指定してください")
    selections = {name: _selection(part, occurrences) for name, part in named.items()}
    rules = song.get("variation", [])
    if not isinstance(rules, list):
        raise _error("variation", "variationは変化の配列で指定してください")
    result = []
    schemas = {"octave_up": {"section", "part", "do"}, "instrument": {"section", "part", "do", "instrument"},
               "rest": {"section", "part", "do"}, "fill_last_bar": {"every", "part", "do"},
               "period": {"section", "part", "do", "beats"}}
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise _error("variation", "変化の各要素はオブジェクトで指定してください")
        name, action = rule.get("part"), rule.get("do")
        if not isinstance(name, str) or name not in named:
            raise _error("variation", "partは実在するパート名で指定してください")
        selected = [o for o in occurrences if o["name"] in selections[name]]
        bar = selected[0]["start_bar"] if selected else 1
        if not isinstance(action, str) or action not in schemas:
            raise _error(name, "doはoctave_up/instrument/rest/fill_last_bar/periodで指定してください", bar)
        if any(field not in schemas[action] for field in rule):
            raise _error(name, f"{action}に未知または併用できない項目があります", bar)
        if action != "period" and ("every" if action == "fill_last_bar" else "section") not in rule:
            raise _error(name, "変化のsection/everyがありません", bar)
        if "section" in rule:
            section = rule["section"]
            if not isinstance(section, str) or section not in {o["name"] for o in occurrences}:
                raise _error(name, "sectionは展開された出現名で指定してください", bar)
            selected = [o for o in selected if o["name"] == section]
        if selected:
            bar = selected[0]["start_bar"]
        part = named[name]
        if action in ("octave_up", "instrument", "period") and _drums(part):
            raise _error(name, f"{action}は有音程パート専用です", bar)
        instrument = rule.get("instrument") if action == "instrument" else None
        if action == "instrument" and (not isinstance(instrument, str) or instrument not in catalog):
            raise _error(name, "instrumentは実在する有音程楽器名で指定してください", bar)
        period = rule.get("beats") if action == "period" else None
        if action == "period":
            if part.get("role") != "chords" or part.get("style") != "arpeggio_up":
                raise _error(name, "periodはrole=chords、style=arpeggio_up専用です", bar)
            if not _finite(period) or period <= 0:
                raise _error(name, "beatsは正の有限数で指定してください", bar)
            end = occurrences[-1]["start_beat"] + occurrences[-1]["bars"] * beats
            try:
                valid = math.isfinite(end / period) and math.isfinite(period / 4) and period / 4 > 0
            except OverflowError:
                valid = False
            if not valid:
                raise _error(name, "beatsは周期位置を有限の正幅で計算できる数にしてください", bar)
        every = rule.get("every") if action == "fill_last_bar" else None
        intervals = []
        if action == "fill_last_bar":
            if type(every) is not int or every <= 0:
                raise _error(name, "everyは正の整数で指定してください", bar)
            _fill_settings(part, song, occurrences, available, bar)
            for occ in selected:
                first, last = occ["start_bar"], occ["start_bar"] + occ["bars"]
                for global_bar in range(((first + every - 1) // every) * every, last, every):
                    start = occ["start_beat"] + (global_bar - first) * beats
                    intervals.append(Interval(start, start + beats, global_bar, occ["occurrence"], occ["name"]))
        else:
            intervals = [_interval(o, beats) for o in selected]
        result.append(Rule(name, action, tuple(intervals), instrument, every, period))
    for index, rule in enumerate(result):
        for other in result[:index]:
            if rule.part != other.part:
                continue
            if rule.action == other.action and rule.action in ("period", "fill_last_bar"):
                raise _error(rule.part, "同じパートのfill/periodはそれぞれ1件だけ指定してください")
            for left in rule.intervals:
                for right in other.intervals:
                    if max(left.start, right.start) < min(left.end, right.end):
                        if rule.action == other.action or "rest" in (rule.action, other.action):
                            raise _error(rule.part, "同じ動作の重複、またはrestと他の変化の重なりがあります",
                                         max(left.start_bar, right.start_bar))
    plan = VariationPlan(tuple(sorted(result, key=lambda r: (r.part, r.action, tuple(i.start for i in r.intervals),
                                                            r.instrument or "", r.every or 0, r.beats or 0))), beats)
    # 空選択でも通常楽器とコピー継承を解決し、存在しない楽器を隠さない。
    resolve_instrument_spans(parts, occurrences, plan, pitched_catalog=catalog)
    return plan


def resolve_instrument_spans(parts, occurrences, plan, *, pitched_catalog):
    """音符の有無によらず、コピー連鎖の楽器だけを区間ごとに継承する。"""
    if not isinstance(plan, VariationPlan) or plan.beats_per_bar not in (3, 4):
        raise _error("variation", "planはcompile_variationの計画で指定してください")
    _occurrences(occurrences, plan.beats_per_bar)
    catalog = _catalog(pitched_catalog)
    order = reference_order(parts, reference_fields=("copy", "source"))
    named, resolved = {p["name"]: p for p in parts}, {}
    end = occurrences[-1]["start_beat"] + occurrences[-1]["bars"] * plan.beats_per_bar
    boundaries = {0, end}
    for rule in plan.rules:
        for interval in rule.intervals:
            boundaries.update((interval.start, interval.end))
    boundaries = sorted(boundaries)
    for name in order:
        part = named[name]
        if _drums(part):
            continue
        if "instrument" not in part and "copy" not in part:
            raise _error(name, "instrumentは実在する有音程楽器名で指定してください")
        if "instrument" in part and (not isinstance(part["instrument"], str) or part["instrument"] not in catalog):
            raise _error(name, "instrumentは実在する有音程楽器名で指定してください")
        spans = []
        for start, stop in zip(boundaries, boundaries[1:], strict=False):
            instrument = part.get("instrument")
            if "instrument" not in part and "copy" in part:
                instrument = next(s.instrument for s in resolved[part["copy"]] if s.start <= start < s.end)
            for rule in plan.rules:
                if rule.part == name and rule.action == "instrument" and any(i.start <= start < i.end for i in rule.intervals):
                    instrument = rule.instrument
            if not isinstance(instrument, str) or instrument not in catalog:
                raise _error(name, "instrumentは実在する有音程楽器名で指定してください",
                             int(start // plan.beats_per_bar) + 1)
            span = InstrumentSpan(name, start, stop, instrument, catalog[instrument])
            if spans and spans[-1].instrument == instrument:
                previous = spans[-1]
                spans[-1] = InstrumentSpan(name, previous.start, stop, instrument, previous.note_range)
            else:
                spans.append(span)
        resolved[name] = spans
    return tuple(s for name in sorted(resolved) for s in resolved[name])


def transform_pitches(part, pitches, *, octave_up=0, note_range=(0, 127), bar=1):
    """移調前の全構成音を共通の整数オクターブ補正で収め、元順序を保つ。"""
    if not isinstance(part, Mapping):
        raise _error("variation", "partはオブジェクトで指定してください", bar)
    name = part.get("name", "variation")
    octave, transpose = part.get("octave", 0), part.get("transpose", 0)
    if type(octave) is not int or type(transpose) is not int or type(octave_up) is not int or octave_up not in (0, 1):
        raise _error(name, "octave/transposeは整数、octave_upは0または1で指定してください", bar)
    low, high = _range(note_range, name, bar)
    if not isinstance(pitches, (list, tuple)) or not pitches or any(type(p) is not int for p in pitches):
        raise _error(name, "構成音は空でない整数の一覧で指定してください", bar)
    tones = [p + 12 * (octave + octave_up) + transpose for p in pitches]
    minimum, maximum = -((min(tones) - low) // 12), (high - max(tones)) // 12
    if minimum > maximum:
        raise _error(name, "全構成音の順序と音程を保って音域に収められません", bar)
    shift = min(max(0, minimum), maximum) * 12
    return [p + shift for p in tones]


def apply_rest(events, intervals, *, drums=False):
    """onsetを除去し直前の持続を切る。元indexで呼出側のidentity/windowを選ぶ。"""
    if type(drums) is not bool or not isinstance(events, (list, tuple)) or not isinstance(intervals, (list, tuple)):
        raise _error("variation", "events/intervalsは一覧、drumsは真偽値で指定してください")
    bounds = []
    for interval in intervals:
        if isinstance(interval, Interval):
            start, stop = interval.start, interval.end
        elif isinstance(interval, (tuple, list)) and len(interval) == 2:
            start, stop = interval
        else:
            raise _error("variation", "休止区間はIntervalまたは開始・終了の組で指定してください")
        if not _finite(start) or not _finite(stop) or not 0 <= start < stop:
            raise _error("variation", "休止区間は有限・非負の開始とそれより後の終了で指定してください")
        bounds.append((start, stop))
    bounds.sort()
    if any(right[0] < left[1] for left, right in zip(bounds, bounds[1:], strict=False)):
        raise _error("variation", "休止区間を重ねて指定できません")
    output, indices, windows = [], [], []
    for index, event in enumerate(events):
        if not isinstance(event, (tuple, list)) or len(event) != (3 if drums else 4):
            raise _error("variation", "音符または打楽器イベントの項目数が不正です")
        beat, voice, velocity = event if drums else (event[0], event[1], event[3])
        if not _finite(beat) or beat < 0 or not _finite(velocity) or not 1 <= velocity <= 127:
            raise _error("variation", "イベントの拍・強さは有限の有効範囲で指定してください")
        if drums:
            if not isinstance(voice, str) or not voice:
                raise _error("variation", "打楽器名は空でない文字列で指定してください")
        elif (not isinstance(voice, (list, tuple)) or not voice or any(type(p) is not int or not 0 <= p <= 127 for p in voice)
              or not _finite(event[2]) or event[2] <= 0 or not _finite(beat + event[2])):
            raise _error("variation", "音符の音高・長さが不正です")
        if any(start <= beat < stop for start, stop in bounds):
            continue
        window = None
        if drums:
            output.append((beat, voice, velocity))
        else:
            duration = event[2]
            cut = next((start for start, _ in bounds if beat < start < beat + duration), None)
            if cut is not None:
                duration, window = cut - beat, (beat, cut)
            output.append((beat, list(voice), duration, velocity))
        indices.append(index)
        windows.append(window)
    return RestResult(output, tuple(indices), tuple(windows))
