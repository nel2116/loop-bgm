"""度数フレーズを既存レンダラーの音符イベントへ変換する。"""

import math
import re
from fractions import Fraction

from bgm.theory import degree_to_midi, parse_key


def compile_melody(part, song, occurrences, *, base_octave=4):
    """展開済みセクションに従い (拍, 音程一覧, 長さ, 強さ) を返す。"""
    name = part.get("name", "melody")

    def field_error(field, message):
        return ValueError(f"[{name}] {field} の指定: {message}")

    try:
        parse_key(song.get("key"))
    except ValueError as exc:
        raise field_error("key", str(exc)) from exc
    grid = part.get("grid")
    meter = song.get("meter")
    if not isinstance(grid, str) or not re.fullmatch(r"1/[1-9][0-9]*", grid):
        raise field_error("grid", "1/8 などの正の分割を指定してください")
    if not isinstance(meter, str) or not re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", meter):
        raise field_error("meter", "4/4 などの拍子を指定してください")
    for field, value in (("grid", grid), ("meter", meter)):
        denominator = int(value.split("/")[1])
        if denominator & (denominator - 1):
            raise field_error(field, "分母は2の累乗で指定してください")
    step = 4 * Fraction(grid)
    bar_beats = 4 * Fraction(meter)
    count = bar_beats / step
    if count.denominator != 1:
        raise field_error("grid", "拍子を均等に分割できません")
    phrases = part.get("phrases")
    if not isinstance(phrases, dict):
        raise field_error("phrases", "セクション名とフレーズの辞書を指定してください")
    selected = part.get("sections")
    if selected is not None:
        names = {occ["name"] for occ in occurrences}
        if not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected):
            raise field_error("sections", "展開されたセクション名の一覧を指定してください")
    octave = part.get("octave", 0)
    transpose = part.get("transpose", 0)
    if type(base_octave) is not int or type(octave) is not int:
        raise field_error("octave", "整数で指定してください")
    if type(transpose) is not int:
        raise field_error("transpose", "半音単位の整数で指定してください")
    velocity = part.get("velocity", 90)
    if type(velocity) not in (int, float) or not 1 <= velocity <= 127 or not math.isfinite(velocity):
        raise field_error("velocity", "1〜127の有限数で指定してください")
    events = []
    for occ in occurrences:
        if selected is not None and occ["name"] not in selected:
            continue

        def error(index, message, occ=occ):
            return ValueError(f"[{name}] {occ['start_bar'] + index}番目の小節: {message} ({occ['name']}/{occ['source']})")

        phrase = phrases.get(occ["source"])
        if not isinstance(phrase, str):
            raise error(0, "phrases に使用するセクションの文字列がありません")
        bars = phrase.split("|")
        if len(bars) != occ["bars"]:
            raise error(min(len(bars), occ["bars"]), f"フレーズは{occ['bars']}小節必要です（実際は{len(bars)}小節）")
        previous = None
        for index, bar in enumerate(bars):
            if not re.fullmatch(r"\s*(?:(?:\[[^\[\]]*\][<>]?|[^\s\[\]]+)(?:\s+|$))*", bar):
                raise error(index, "音符と和音は空白で区切ってください")
            tokens = re.findall(r"\[[^\[\]]*\][<>]?|[^\s]+", bar)
            if len(tokens) != count:
                raise error(index, f"grid に対して{int(count)}個の音符が必要です（実際は{len(tokens)}個）")
            for position, token in enumerate(tokens):
                if token == ".":
                    previous = None
                    continue
                if token == "-":
                    if previous is None:
                        raise error(index, "伸ばし記号の直前に音符がありません")
                    beat, pitches, duration, vel = events[previous]
                    events[previous] = (beat, pitches, duration + float(step), vel)
                    continue
                factor = 1.2 if token.endswith(">") else 0.8 if token.endswith("<") else 1
                body = token[:-1] if token.endswith((">", "<")) else token
                degrees = body[1:-1].split() if body.startswith("[") and body.endswith("]") else [body]
                if not degrees:
                    raise error(index, "和音に度数がありません")
                try:
                    pitches = [degree_to_midi(d, song["key"], base_octave=base_octave + octave) + transpose for d in degrees]
                    if any(not 0 <= pitch <= 127 for pitch in pitches):
                        raise ValueError("移調後の音程がMIDIの範囲（0〜127）を超えています")
                except ValueError as exc:
                    raise error(index, str(exc)) from exc
                beat = occ["start_beat"] + float(index * bar_beats + position * step)
                events.append((beat, pitches, float(step), max(1, min(127, round(velocity * factor)))))
                previous = len(events) - 1
    return events
