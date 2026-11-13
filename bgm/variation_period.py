"""曲頭の周期位相で分散和音を生成する純粋API。描画への接続は別途行う。"""

import math
from fractions import Fraction

_METERS = {"4/4": (4, (0, 2)), "3/4": (3, (0,)), "6/8": (3, (0, 1.5))}


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def compile_period(part, song, occurrences, harmony, *, period_beats, section=None):
    """既存tuple形式のraw eventsと並列metadataを新規配列で返す。

    現和声のn音について候補cP+iP/nを使い、曲頭からの位相を維持する。
    eventsの音高は原和声のまま。metadataのharmony_index/tonesで全voicingを
    取得し、呼出し側がoctave/octave_up、transpose、共通音域補正後に選音する。
    window/ordinal/tonesは既存描画用、occurrence/cycle/slotは元イベント情報。
    gate/strum/swing/humanize、楽器選択、rest、音源読込は実行しない。
    section=Noneは省略を表す。JSONの明示nullや規則全体は上位validatorが検査する。
    """
    name = part.get("name", "period") if isinstance(part, dict) else "period"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/song はオブジェクトで指定してください")
    if part.get("role") != "chords" or part.get("type", "notes") != "notes" or part.get("style") != "arpeggio_up":
        raise error("period は role=chords、type=notes、style=arpeggio_up のパートに指定してください")
    if any(k in part for k in ("bars", "phrases", "grid", "copy", "accent", "source", "groove", "kit", "voices")):
        raise error("period と bars/phrases/grid/copy/accent/source/groove/kit/voices は併用できません")
    if not _finite(period_beats) or period_beats <= 0:
        raise error("period beats は正の有限数で指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in _METERS:
        raise error("meter は 4/4、3/4、6/8 に対応しています")
    beats, accents = _METERS[meter]
    velocity = part.get("velocity", 90)
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise error("velocity は1〜127の有限数で指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrences は空でない一覧で指定してください")
    end, next_bar, by_occurrence = 0, 1, []
    for index, occ in enumerate(occurrences):
        if not isinstance(occ, dict):
            raise error("occurrences の各要素はオブジェクトで指定してください")
        start, bars, bar = (occ.get(k) for k in ("start_beat", "bars", "start_bar"))
        if (not _finite(start) or start != end or type(bars) is not int or bars <= 0
                or type(bar) is not int or bar != next_bar or type(occ.get("occurrence")) is not int or occ["occurrence"] != index
                or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))):
            raise error("出現の名前・順序・開始拍・小節位置が不正です", next_bar)
        length = bars * beats
        if not _finite(length) or not _finite(start + length) or start + length <= start:
            raise error("出現の終端を有限で区別できる拍として計算できません", bar)
        end = start + length
        next_bar += bars
        by_occurrence.append([])
    names = {o["name"] for o in occurrences}
    selected = part.get("sections", list(names))
    if (not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected)
            or len(set(selected)) != len(selected)):
        raise error("sections は重複しない出現名の一覧で指定してください")
    if section is not None and (not isinstance(section, str) or section not in names):
        raise error("period section は存在する出現名で指定してください")
    if not isinstance(harmony, list) or not harmony:
        raise error("harmony は空でない和声一覧で指定してください")
    previous, occurrence_index = -1, 0
    for index, chord in enumerate(harmony):
        if not isinstance(chord, dict):
            raise error("harmony の各要素はオブジェクトで指定してください")
        beat, duration, bar = (chord.get(k) for k in ("beat", "duration", "bar"))
        if (not _finite(beat) or not 0 <= beat < end or beat <= previous
                or not _finite(duration) or duration <= 0 or not _finite(beat + duration) or beat + duration <= beat):
            raise error("和声の拍・長さは順序どおりの有限な正区間で指定してください", bar if type(bar) is int and bar > 0 else 1)
        while occurrence_index + 1 < len(occurrences) and beat >= occurrences[occurrence_index + 1]["start_beat"]:
            occurrence_index += 1
        occ = occurrences[occurrence_index]
        actual_bar = occ["start_bar"] + int((beat - occ["start_beat"]) // beats)
        if (type(bar) is not int or bar != actual_bar or chord.get("section") != occ["name"] or chord.get("source") != occ["source"]):
            raise error("和声の出現名・素材・小節位置が一致しません", actual_bar)
        pitches = chord.get("pitches")
        if (not isinstance(pitches, list) or not pitches
                or any(type(p) is not int or not 0 <= p <= 127 for p in pitches)):
            raise error("和声の pitches は0〜127のMIDI整数の空でない一覧で指定してください", bar)
        by_occurrence[occurrence_index].append(index)
        previous = beat

    period = Fraction(period_beats)
    # 累積加算を避けてもfloatで別発音を区別できない周期は扱えない。
    for occ, indices in zip(occurrences, by_occurrence, strict=True):
        if not indices or harmony[indices[0]]["beat"] != occ["start_beat"]:
            raise error("harmony が出現の先頭から必要です", occ["start_bar"])
        stop = occ["start_beat"] + occ["bars"] * beats
        for position, index in enumerate(indices):
            chord = harmony[index]
            right = harmony[indices[position + 1]]["beat"] if position + 1 < len(indices) else stop
            written_end = chord["beat"] + chord["duration"]
            if written_end < right and right - written_end > max(math.ulp(float(right)), math.ulp(float(written_end))) * 2:
                raise error("harmony に空白があります", chord["bar"])
            spacing = period / len(chord["pitches"])
            if spacing <= Fraction(math.ulp(float(right))) and float(Fraction(right) + spacing) == float(right):
                raise error("period beats が小さすぎて発音拍を区別できません", chord["bar"])

    events, metadata = [], []
    for occ, indices in zip(occurrences, by_occurrence, strict=True):
        if occ["name"] not in selected or section is not None and occ["name"] != section:
            continue
        stop = occ["start_beat"] + occ["bars"] * beats
        for position, index in enumerate(indices):
            chord = harmony[index]
            left = chord["beat"]
            right = min(stop, chord["beat"] + chord["duration"])
            if position + 1 < len(indices):
                right = min(right, harmony[indices[position + 1]]["beat"])
            n = len(chord["pitches"])
            spacing = period / n
            # 境界と同じfloatに丸められる候補も半開区間へ一意に所属させる。
            first = max(0, Fraction(left) // spacing - 1)
            last = Fraction(right) // spacing + 1
            for step in range(first, last + 1):
                rational_beat = step * spacing
                if rational_beat > Fraction(right) + Fraction(math.ulp(float(right))):
                    break
                beat = float(rational_beat)
                if not left <= beat < right:
                    continue
                slot = step % n
                duration = min(.4, float(spacing), right - beat)
                if duration <= 0 or not _finite(duration):
                    raise error("period の発音長を正の有限数で計算できません", chord["bar"])
                local = (beat - occ["start_beat"]) % beats
                strong = any(math.isclose(local, a, rel_tol=0, abs_tol=1e-9) for a in accents)
                vel = max(1, min(127, round(velocity * (1.2 if strong else 1))))
                events.append((beat, [chord["pitches"][slot]], duration, vel))
                metadata.append({"window": [left, right], "ordinal": 0, "tones": [slot], "harmony_index": index,
                                 "occurrence": occ["occurrence"], "cycle": step // n, "slot": slot})
    return {"events": events, "metadata": metadata}
