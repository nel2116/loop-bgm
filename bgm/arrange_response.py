"""記譜上のメロディの休みに、固定の合いの手を生成する。"""

import math

_METERS = {"4/4": (4, (0, 2)), "3/4": (3, (0,)), "6/8": (3, (0, 1.5))}


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def compile_counter(part, song, occurrences, harmony, source_events, *, note_range=(0, 127)):
    """gate前の占有を差し引き、区間頭から半拍ごとの根音を返す。

    戻り値は既存の (拍, MIDI一覧, 記譜長, 強さ)。独立対旋律の直接記述、
    参照グラフの解決、音源の検査、DSPとそのhard windowは呼び出し側が担当する。
    """
    name = part.get("name", "counter") if isinstance(part, dict) else "counter"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/songはオブジェクトで指定してください")
    if part.get("role") != "arrange" or part.get("type", "notes") != "notes" or part.get("accent") != "counter":
        raise error("role=arrange、type=notes、accent=counterで指定してください")
    if any(field in part for field in ("copy", "style", "groove", "bars", "phrases", "grid", "kit", "voices")):
        raise error("counterとcopy/style/groove/bars/phrases/grid/kit/voicesは併用できません（空の指定も含む）")
    if not isinstance(part.get("instrument"), str) or not part["instrument"]:
        raise error("instrumentは空でない楽器名で指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in _METERS:
        raise error("meterは4/4、3/4、6/8に対応しています")
    bpb, strong = _METERS[meter]
    octave, transpose, velocity = part.get("octave", 0), part.get("transpose", 0), part.get("velocity", 90)
    if type(octave) is not int or type(transpose) is not int:
        raise error("octave/transposeは整数で指定してください")
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise error("velocityは1〜127の有限数で指定してください")
    if (not isinstance(note_range, (tuple, list)) or len(note_range) != 2
            or any(type(p) is not int for p in note_range) or not 0 <= note_range[0] <= note_range[1] <= 127):
        raise error("note_rangeは0〜127の整数の下限・上限で指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrencesは空でないリストで指定してください")
    end, next_bar = 0, 1
    for occ in occurrences:
        if (not isinstance(occ, dict) or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("bars")) is not int or occ["bars"] < 1
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or not _finite(occ.get("start_beat")) or occ["start_beat"] != end):
            raise error("occurrencesの名前・素材・小節・開始位置が不正です", next_bar)
        end += occ["bars"] * bpb
        next_bar += occ["bars"]
        if not _finite(end):
            raise error("曲の長さを有限数で計算できません")
    names = {o["name"] for o in occurrences}

    def selection(p):
        selected = p.get("sections")
        if "sections" in p and (not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected)):
            raise error("sectionsは展開されたセクション名のリストで指定してください")
        return names if selected is None else set(selected)

    source = part.get("source")
    parts = song.get("parts")
    if not isinstance(source, str) or not source or source == name or not isinstance(parts, list):
        raise error("sourceは直接記述した別のmelodyパート名で指定してください")
    sources = [p for p in parts if isinstance(p, dict) and p.get("name") == source]
    if len(sources) != 1:
        raise error("sourceの参照先が未定義または重複しています")
    source_part = sources[0]
    if (source_part.get("role") != "melody" or source_part.get("type", "notes") != "notes"
            or any(f in source_part for f in ("copy", "accent", "source", "style", "groove"))
            or not ("bars" in source_part or "phrases" in source_part and "grid" in source_part)
            or "bars" in source_part and any(f in source_part for f in ("phrases", "grid"))):
        raise error("sourceはbarsまたはphrases/gridで直接記述したrole=melodyに限ります")
    selected = selection(part) & selection(source_part)
    if not isinstance(source_events, list):
        raise error("source_eventsは音符イベントのリストで指定してください")
    occupied = []
    for event in source_events:
        if not isinstance(event, (list, tuple)) or len(event) != 4:
            raise error("参照音符は拍・音程一覧・長さ・強さの4項目で指定してください")
        beat, pitches, duration, vel = event
        if (not _finite(beat) or not 0 <= beat < end or not _finite(duration) or duration <= 0
                or not _finite(beat + duration) or not _finite(vel) or not 1 <= vel <= 127
                or not isinstance(pitches, list) or not pitches or any(type(p) is not int or not 0 <= p <= 127 for p in pitches)):
            raise error("参照音符の拍・音程・長さ・強さが不正です")
        occupied.append((beat, min(beat + duration, end)))
    merged = []
    for start, stop in sorted(occupied):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
        else:
            merged.append((start, stop))
    if not isinstance(harmony, list):
        raise error("harmonyは和声のリストで指定してください")
    by_bar = {}
    previous = -1
    for chord in harmony:
        if not isinstance(chord, dict) or type(chord.get("bar")) is not int or not 1 <= chord["bar"] < next_bar:
            raise error("harmonyの小節位置が不正です")
        bar = chord["bar"]
        beat, duration = chord.get("beat"), chord.get("duration")
        if (not _finite(beat) or beat <= previous or not 0 <= beat < end
                or not _finite(duration) or not 0 < duration <= bpb or not _finite(beat + duration)
                or type(chord.get("root")) is not int or not 0 <= chord["root"] <= 127
                or any(not isinstance(chord.get(k), str) or not chord[k] for k in ("section", "source"))
                or not isinstance(chord.get("pitches"), list) or not chord["pitches"]
                or any(type(p) is not int or not 0 <= p <= 127 for p in chord["pitches"])):
            raise error("harmonyの拍・長さ・根音・構成音・セクションが不正です", bar)
        previous = beat
        by_bar.setdefault(bar, []).append(chord)
    events = []
    for occ in occurrences:
        for index in range(occ["bars"]):
            bar = occ["start_bar"] + index
            start = occ["start_beat"] + index * bpb
            stop = start + bpb
            chords = by_bar.get(bar, [])
            cursor = start
            for chord in chords:
                if (chord["section"] != occ["name"] or chord["source"] != occ["source"]
                        or not math.isclose(chord["beat"], cursor, rel_tol=0, abs_tol=1e-9)):
                    raise error("harmonyのセクションまたは連続する拍位置が一致しません", bar)
                cursor = chord["beat"] + chord["duration"]
            if not chords or not math.isclose(cursor, stop, rel_tol=0, abs_tol=1e-9):
                raise error("harmonyが小節を過不足なく埋めていません", bar)
            if occ["name"] not in selected:
                continue
            for chord in chords:
                left, right = chord["beat"], min(chord["beat"] + chord["duration"], stop)
                gaps = []
                for onset, offset in merged:
                    if offset <= left or onset >= right:
                        continue
                    if onset > left:
                        gaps.append((left, onset))
                    left = max(left, offset)
                    if left >= right:
                        break
                if left < right:
                    gaps.append((left, right))
                pitch = chord["root"] + 12 + octave * 12 + transpose
                low, high = note_range
                lower, upper = -((pitch - low) // 12), (high - pitch) // 12
                if lower > upper:
                    raise error("根音をオクターブ補正で音域内に収められません", bar)
                pitch += min(max(0, lower), upper) * 12
                for left, right in gaps:
                    # 半拍を確保できない断片には発音しない。境界ごとに位相を戻す。
                    step = 0
                    while (right - (left + step * 0.5) >= 0.5
                           or math.isclose(right - (left + step * 0.5), 0.5, rel_tol=0, abs_tol=1e-9)):
                        beat = left + step * 0.5
                        factor = 1 if any(math.isclose(beat - start, s, rel_tol=0, abs_tol=1e-9) for s in strong) else 0.8
                        events.append((beat, [pitch], min(0.4, right - beat), max(1, min(127, round(velocity * factor)))))
                        step += 1
    return events
