"""展開済み和声から決定的なベース伴奏を作る。"""

import math


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def compile_bass(part, song, occurrences, harmony, *, note_range=(0, 127)):
    """和声の伴奏を (拍, MIDI一覧, 長さ, velocity) で返す。

    arpeggioは転回後の構成音、他はrootを1オクターブ下げて相対移調する。
    音源を参照せず、呼び出し側から渡された音域へオクターブ補正する。
    """
    name = part.get("name", "bass") if isinstance(part, dict) else "bass"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/songはオブジェクトで指定してください")
    style = part.get("style")
    if style not in ("root_whole", "root_quarter", "root_fifth", "octave_8th", "walking", "arpeggio"):
        raise error("styleはroot_whole/root_quarter/root_fifth/octave_8th/walking/arpeggioから指定してください")
    if part.get("role", "bass") != "bass" or part.get("type", "notes") != "notes":
        raise error("ベース伴奏はrole=bass、type=notesで指定してください")
    if any(field in part for field in ("bars", "phrases", "grid", "groove")):
        raise error("styleとbars/phrases/grid/grooveは併用できません（空の指定も含む）")
    meter = song.get("meter")
    if meter not in ("4/4", "3/4", "6/8"):
        raise error("meterは4/4、3/4、6/8から指定してください")
    bar_beats = 4 if meter == "4/4" else 3
    octave, transpose = part.get("octave", 0), part.get("transpose", 0)
    if type(octave) is not int or type(transpose) is not int:
        raise error("octaveとtransposeは整数で指定してください")
    velocity = part.get("velocity", 90)
    if not _number(velocity) or not 1 <= velocity <= 127:
        raise error("velocityは1〜127の有限数で指定してください")
    if (not isinstance(note_range, (tuple, list)) or len(note_range) != 2
            or any(type(n) is not int for n in note_range) or not 0 <= note_range[0] <= note_range[1] <= 127):
        raise error("note_rangeは0〜127の整数の下限・上限で指定してください")
    if not isinstance(occurrences, list) or not occurrences or not isinstance(harmony, list):
        raise error("occurrencesは空でないリスト、harmonyはリストで指定してください")
    end = 0
    next_bar = 1
    for occ in occurrences:
        if (not isinstance(occ, dict) or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or type(occ.get("bars")) is not int or occ["bars"] < 1
                or not _number(occ.get("start_beat")) or occ["start_beat"] != end):
            raise error("occurrencesの名前・素材・小節・開始位置が不正です", next_bar)
        end += occ["bars"] * bar_beats
        next_bar += occ["bars"]
    selected = part.get("sections")
    if "sections" in part and (not isinstance(selected, list)
                              or any(not isinstance(s, str) or s not in {o["name"] for o in occurrences} for s in selected)):
        raise error("sectionsは展開されたセクション名のリストで指定してください")
    by_bar = {}
    for chord in harmony:
        if not isinstance(chord, dict) or type(chord.get("bar")) is not int or not 1 <= chord["bar"] < next_bar:
            raise error("harmonyの小節位置が不正です")
        bar = chord["bar"]
        if (not _number(chord.get("beat")) or not 0 <= chord["beat"] < end
                or not _number(chord.get("duration")) or not 0 < chord["duration"] <= bar_beats
                or type(chord.get("root")) is not int or not 0 <= chord["root"] <= 127
                or chord.get("quality") not in ("major", "minor", "diminished", "sus4")):
            raise error("harmonyの開始拍・長さ・根音・品質が不正です", bar)
        by_bar.setdefault(bar, []).append(chord)
        if style == "arpeggio" and (not isinstance(chord.get("pitches"), list) or not chord["pitches"]
                                     or any(type(p) is not int or not 0 <= p <= 127 for p in chord["pitches"])
                                     or chord["pitches"] != sorted(chord["pitches"])):
            raise error("harmonyの構成音は昇順のMIDI整数リストで指定してください", bar)
    # 入力の並び順によらず、直後の実際の和声を参照する。
    ordered = sorted(harmony, key=lambda c: c["beat"])
    following = {id(c): ordered[(i + 1) % len(ordered)] for i, c in enumerate(ordered)}
    events = []
    for occ in occurrences:
        for index in range(occ["bars"]):
            bar = occ["start_bar"] + index
            start = occ["start_beat"] + index * bar_beats
            stop = start + bar_beats
            chords = by_bar.get(bar, [])
            cursor = start
            for chord in chords:
                if (chord.get("section") != occ["name"] or chord.get("source") != occ["source"]
                        or not math.isclose(chord["beat"], cursor, rel_tol=0, abs_tol=1e-9)):
                    raise error("harmonyのセクションまたは連続する拍位置が一致しません", bar)
                cursor = chord["beat"] + chord["duration"]
            if not chords or not math.isclose(cursor, stop, rel_tol=0, abs_tol=1e-9):
                raise error("harmonyが小節を過不足なく埋めていません", bar)
            if selected is not None and occ["name"] not in selected:
                continue
            if style == "root_whole":
                pattern = {0: False}
            elif style == "root_quarter":
                pattern = dict.fromkeys(range(bar_beats), False)
            elif style == "root_fifth":
                pattern = {0: False, 1.5 if meter == "6/8" else 2: True}
            else:
                step = 1 if style == "walking" else 0.5
                pattern = dict.fromkeys((i * step for i in range(int(bar_beats / step))), False)
            attacks = {start + offset: fifth for offset, fifth in pattern.items()}
            for chord in chords:
                # 同時刻の固定パターンより和声境界の音列先頭を優先する。
                for beat in list(attacks):
                    if math.isclose(beat, chord["beat"], rel_tol=0, abs_tol=1e-9):
                        del attacks[beat]
                attacks[chord["beat"]] = False
            times = sorted(attacks)
            chord_index = 0
            tone_index = 0
            for i, beat in enumerate(times):
                while chord_index + 1 < len(chords) and chords[chord_index + 1]["beat"] <= beat:
                    chord_index += 1
                chord = chords[chord_index]
                if math.isclose(beat, chord["beat"], rel_tol=0, abs_tol=1e-9):
                    tone_index = 0
                pitch = chord["root"] - 12 + octave * 12 + transpose
                if attacks[beat]:
                    pitch += 6 if chord["quality"] == "diminished" else 7
                if style == "octave_8th":
                    pitch += 12 * (tone_index % 2)
                elif style == "walking":
                    third = 4 if chord["quality"] == "major" else 5 if chord["quality"] == "sus4" else 3
                    pitch += (0, third, 6 if chord["quality"] == "diminished" else 7)[tone_index % 3]
                    target = following[id(chord)]
                    # beat+durationの丸め差を避け、次和声の実際の開始位置を使う。
                    chord_stop = chords[chord_index + 1]["beat"] if chord_index + 1 < len(chords) else stop
                    last = i + 1 == len(times) or times[i + 1] >= chord_stop
                    if tone_index > 0 and last and (selected is None or target.get("section") in selected):
                        pitch = target["root"] - 13 + octave * 12 + transpose
                elif style == "arpeggio":
                    tones = [p - 12 + octave * 12 + transpose for p in chord["pitches"]]
                    low, high = note_range
                    lower = -((min(tones) - low) // 12)
                    upper = (high - max(tones)) // 12
                    if lower > upper:
                        raise error("全構成音を共通のオクターブ補正で音域内に収められません", bar)
                    shift = min(max(0, lower), upper)
                    pitch = tones[tone_index % len(tones)] + shift * 12
                tone_index += 1
                if style != "arpeggio":
                    low, high = note_range
                    # 整数演算で巨大な移調にも対応し、同距離なら低い音を選ぶ。
                    lower = -((pitch - low) // 12)
                    upper = (high - pitch) // 12
                    if lower > upper:
                        raise error("オクターブ補正で音域内に収められません", bar)
                    shift = min(max(0, lower), upper)
                    pitch += shift * 12
                next_attack = times[i + 1] if i + 1 < len(times) else stop
                duration = (next_attack - beat) * (1 if style == "root_whole" else 0.9)
                duration = min(duration, chord["beat"] + chord["duration"] - beat, stop - beat, end - beat)
                offset = beat - start
                strong = (0, 2) if meter == "4/4" else (0, 1.5) if meter == "6/8" else (0,)
                factor = 1 if any(math.isclose(offset, s, rel_tol=0, abs_tol=1e-9) for s in strong) else 0.8
                events.append((beat, [pitch], duration, max(1, min(127, round(velocity * factor)))))
    return events
