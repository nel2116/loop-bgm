"""展開済み和声から、音源を読み込まずコード伴奏を生成する。"""

import math

_METERS = {"4/4": (4, (0, 2)), "3/4": (3, (0,)), "6/8": (3, (0, 1.5))}
_STYLES = ("pad", "block", "offbeat", "arpeggio_up", "broken", "strum", "waltz")


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def compile_chords(part, song, occurrences, harmony, *, note_range=(0, 127)):
    """承認済みの固定拍型を (拍, MIDI一覧, 長さ, 強さ) へ変換する。

    padは各和声開始から持続、blockは四分拍ごとに0.8拍、offbeatは
    各四分拍の裏から0.4拍。分散2型は八分拍ごとに0.4拍、strumは
    四分拍ごとに全構成音を0.8拍。strumの秒単位の遅延は描画側が担う。
    waltzは3/4の0拍に最低音、1・2拍に残りの構成音を0.8拍。
    6/8も四分拍単位で、強拍のみ0と1.5。
    長さは和声・出現・曲の終端で切り、入力の和音は共通オクターブで移す。
    """
    name = part.get("name", "chords") if isinstance(part, dict) else "chords"

    def error(message, bar=None):
        location = f"{bar}番目の小節" if bar is not None else "指定"
        return ValueError(f"[{name}] {location}: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/song はオブジェクトで指定してください")
    if part.get("role") != "chords" or part.get("type", "notes") != "notes":
        raise error("コード伴奏は role=chords、type=notes で指定してください")
    if any(field in part for field in ("bars", "phrases", "grid", "groove")):
        raise error("style と bars/phrases/grid/groove は同時に指定できません")
    style = part.get("style")
    if not isinstance(style, str) or style not in _STYLES:
        raise error(f"style は {'/'.join(_STYLES)} から指定してください")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in _METERS:
        raise error("meter は 4/4、3/4、6/8 に対応しています")
    bar_beats, accents = _METERS[meter]
    if style == "waltz" and meter != "3/4":
        raise error("style=waltz は meter=3/4 にのみ対応しています", 1)
    octave, transpose = part.get("octave", 0), part.get("transpose", 0)
    if type(octave) is not int or type(transpose) is not int:
        raise error("octave/transpose は整数で指定してください")
    velocity = part.get("velocity", 90)
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise error("velocity は1〜127の有限数で指定してください")
    if (not isinstance(note_range, (tuple, list)) or len(note_range) != 2
            or any(type(pitch) is not int for pitch in note_range)
            or not 0 <= note_range[0] <= note_range[1] <= 127):
        raise error("note_range は0〜127の整数の下限・上限で指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrences は空でないリストで指定してください")
    last_end = 0
    for occ in occurrences:
        if not isinstance(occ, dict):
            raise error("occurrences の各要素はオブジェクトで指定してください")
        start, bar, bars = (occ.get(field) for field in ("start_beat", "start_bar", "bars"))
        if (type(bar) is not int or bar < 1 or type(bars) is not int or bars < 1
                or not _finite(start) or start < 0):
            raise error("出現の start_beat/start_bar/bars が不正です")
        if any(not isinstance(occ.get(field), str) or not occ[field] for field in ("name", "source")):
            raise error("出現の name/source は空でない文字列で指定してください", bar)
        if not _finite(bars * bar_beats):
            raise error("出現の長さを有限数で計算できません", bar)
        end = start + bars * bar_beats
        if not _finite(end) or start < last_end:
            raise error("出現の時刻は有限で、順序どおり重ならず指定してください", bar)
        last_end = end
    song_end = last_end
    selected = part.get("sections")
    if "sections" in part:
        names = {occ["name"] for occ in occurrences}
        if not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected):
            raise error("sections は展開された出現名の一覧で指定してください")
    if not isinstance(harmony, list) or not harmony:
        raise error("harmony は空でないリストで指定してください")
    previous = -1
    for chord in harmony:
        if not isinstance(chord, dict):
            raise error("harmony の各要素はオブジェクトで指定してください")
        bar, beat, duration = (chord.get(field) for field in ("bar", "beat", "duration"))
        if type(bar) is not int or bar < 1:
            raise error("和声の bar は正の整数で指定してください")
        if (not _finite(beat) or beat < 0 or beat <= previous
                or not _finite(duration) or duration <= 0 or not _finite(beat + duration)):
            raise error("和声の beat/duration は順序どおりの有限な正の区間で指定してください", bar)
        if any(not isinstance(chord.get(field), str) or not chord[field] for field in ("section", "source")):
            raise error("和声の section/source が不正です", bar)
        pitches = chord.get("pitches")
        if (not isinstance(pitches, list) or not pitches
                or any(type(pitch) is not int or not 0 <= pitch <= 127 for pitch in pitches)):
            raise error("和声の pitches はMIDI整数の空でない一覧で指定してください", bar)
        previous = beat

    events = []
    for occ in occurrences:
        if selected is not None and occ["name"] not in selected:
            continue
        start = occ["start_beat"]
        end = min(start + occ["bars"] * bar_beats, song_end)
        for index, chord in enumerate(harmony):
            beat = chord["beat"]
            if not start <= beat < end or chord["section"] != occ["name"] or chord["source"] != occ["source"]:
                continue
            boundary = min(beat + chord["duration"], end)
            if index + 1 < len(harmony):
                boundary = min(boundary, harmony[index + 1]["beat"])
            pitches = [pitch + octave * 12 + transpose for pitch in chord["pitches"]]
            low, high = note_range
            minimum = -((min(pitches) - low) // 12)
            maximum = (high - max(pitches)) // 12
            if minimum > maximum:
                raise error("転回形と音程間隔を保ったまま全構成音を音域に収められません", chord["bar"])
            shift = min(max(0, minimum), maximum) * 12
            pitches = [pitch + shift for pitch in pitches]
            if style == "pad":
                positions = [beat]
            elif style in ("arpeggio_up", "broken"):
                first = max(0, math.ceil((beat - start) * 2))
                positions = (start + step / 2 for step in range(first, occ["bars"] * bar_beats * 2))
            else:
                # 和声変化でグリッドを動かさず、境界への追加発音もしない。
                offset = 0.5 if style == "offbeat" else 0
                first = max(0, math.ceil(beat - start - offset))
                positions = (start + position + offset for position in range(first, occ["bars"] * bar_beats))
            for position in positions:
                if position >= boundary:
                    break
                short = style in ("offbeat", "arpeggio_up", "broken")
                duration = boundary - position if style == "pad" else min(0.4 if short else 0.8, boundary - position)
                local = (position - start) % bar_beats
                tones = list(pitches)
                if style in ("arpeggio_up", "broken"):
                    # 和声変更では位相を変えず、小節内の八分拍番号で選ぶ。
                    step = round(local * 2)
                    order = list(range(len(pitches)))
                    if style == "broken":
                        order = [i for pair in zip(order, reversed(order), strict=True) for i in pair][:len(pitches)]
                    tones = [pitches[order[step % len(order)]]]
                elif style == "waltz":
                    tones = pitches[:1] if local == 0 else pitches[1:]
                    if not tones:
                        continue
                strong = any(math.isclose(local, accent, abs_tol=1e-9, rel_tol=0) for accent in accents)
                vel = max(1, min(127, round(velocity * (1.2 if strong else 1))))
                events.append((position, tones, duration, vel))
    return events
