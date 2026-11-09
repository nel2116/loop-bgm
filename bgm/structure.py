"""拍子とセクション構成を四分音符単位の時刻へ展開する。"""

import re
from collections.abc import Mapping
from fractions import Fraction


def _ratio(value, field):
    if not isinstance(value, str) or not (match := re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", value)):
        raise ValueError(f"{field}: 正の整数の分数で指定してください（例: 4/4）")
    numerator, denominator = map(int, match.groups())
    if denominator & (denominator - 1):
        raise ValueError(f"{field}: 分母は2の累乗で指定してください")
    return numerator, denominator


def meter_to_beats(meter) -> float:
    """拍子の1小節を四分音符単位で返す。"""
    numerator, denominator = _ratio(meter, "meter（拍子）")
    return float(Fraction(numerator * 4, denominator))


def grid_to_beats(grid) -> float:
    """1/n 音符の長さを四分音符単位で返す。"""
    numerator, denominator = _ratio(grid, "grid（音符の長さ）")
    if numerator != 1:
        raise ValueError("grid（音符の長さ）: 1/n の形式で指定してください")
    return float(Fraction(4, denominator))


def _source(name):
    if not isinstance(name, str) or not name or name != name.strip() or not name.rstrip("'"):
        raise ValueError("セクション名: 空でない名前を指定してください")
    return name.rstrip("'")


def expand_form(song) -> list[dict]:
    """入力を変更せず、各出現の名前・参照元・開始位置を返す。"""
    if not isinstance(song, Mapping):
        raise ValueError("曲: オブジェクトで指定してください")
    beats = meter_to_beats(song.get("meter"))
    form = song.get("form")
    sections = song.get("sections")
    if not isinstance(form, list) or not form:
        raise ValueError("form（構成）: セクション名の空でない配列を指定してください")
    if not isinstance(sections, Mapping) or not sections:
        raise ValueError("sections（セクション定義）: 空でないオブジェクトを指定してください")
    for name, section in sections.items():
        source = _source(name)
        if not isinstance(section, Mapping):
            raise ValueError(f"sections[{name!r}]: オブジェクトで指定してください")
        bars = section.get("bars")
        if isinstance(bars, bool) or not isinstance(bars, int) or bars <= 0:
            raise ValueError(f"sections[{name!r}].bars: 正の整数の小節数を指定してください")
        if source != name:
            if source not in sections:
                raise ValueError(f"sections[{name!r}]: 参照元 {source!r} が未定義です")
            if section != sections[source]:
                raise ValueError(f"sections[{name!r}]: 参照元 {source!r} と競合する定義です")
    result = []
    elapsed_bars = 0
    for index, name in enumerate(form):
        source = _source(name)
        if source not in sections:
            raise ValueError(f"form[{index}]: 参照元 {source!r} が未定義です")
        bars = sections[source]["bars"]
        result.append({
            "name": name, "source": source, "occurrence": index,
            "start_beat": elapsed_bars * beats, "start_bar": elapsed_bars + 1, "bars": bars,
        })
        elapsed_bars += bars
    return result
