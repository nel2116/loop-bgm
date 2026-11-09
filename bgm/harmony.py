"""ローマ数字を音源に依存しない和音データへ変換する。"""

import math
import re

from .theory import degree_to_midi, parse_key

_ROMANS = ("I", "II", "III", "IV", "V", "VI", "VII")
_NORMAL = ("I", "ii", "iii", "IV", "V", "vi", "vii°")
_MINOR = ("i", "ii°", "III", "iv", "v", "VI", "VII")
_QUALITIES = {
    "major": ("major", "minor", "minor", "major", "major", "minor", "diminished"),
    "minor": ("minor", "diminished", "major", "minor", "major", "major", "major"),
}
_CHORD = re.compile(r"([b#]?)(VII|III|VI|IV|II|V|I|vii|iii|vi|iv|ii|v|i)(°?)(maj7|sus4|add9|7)?(/3)?")


def parse_roman_chord(token, key, *, base_octave=3):
    """和音のMIDI構成音と役割を返す（入力は変更しない）。

    通常役割は調追従し、短調でもVは長和音、vは短和音となる。
    長調のivと先頭b/#は明示借用。b/#の根音は同主長調基準。
    単独の7は+10（減三和音では半減七）、maj7は+11、add9は+14。
    完全減七(+9)と複合接尾辞は未対応。sus4は常に0,5,7。
    /3は第三音をbassにする第一転回。sus4/3は拒否する。

    tokenは入力表記、degreeは1〜7、accidentalは-1/0/1、roleは
    解決後の品質と変化記号を含むローマ数字（接尾辞・転回なし）。
    qualityはmajor/minor/diminished/sus4、extensionは接尾辞かNone、
    inversionは0/1、borrowedは明示借用かどうか。
    rootは転回前の根音MIDI、bassは転回後の最低音、pitchesは昇順MIDI。
    """
    _, mode = parse_key(key)
    match = _CHORD.fullmatch(token) if isinstance(token, str) else None
    if match is None:
        raise ValueError(f"コードが読めません: {token!r}")
    accidental, roman, diminished, extension, inversion = match.groups()
    degree = _ROMANS.index(roman.upper()) + 1
    symbol = roman + diminished
    borrowed = bool(accidental) or (mode == "major" and symbol == "iv")
    if accidental:
        quality = "diminished" if diminished else "major" if roman.isupper() else "minor"
    elif borrowed:
        quality = "minor"
    else:
        allowed = set(_NORMAL) | (set(_MINOR) if mode == "minor" else set())
        if symbol not in allowed:
            raise ValueError(f"この調ではコード表記 {symbol!r} を使えません")
        quality = "minor" if symbol == "v" else _QUALITIES[mode][degree - 1]
    root_key = key.strip().rsplit(" ", 1)[0] + " major" if accidental else key
    root = degree_to_midi(f"{accidental}{degree}", root_key, base_octave=base_octave)
    role = _ROMANS[degree - 1]
    if quality != "major":
        role = role.lower() + ("°" if quality == "diminished" else "")
    role = accidental + role
    intervals = {"major": [0, 4, 7], "minor": [0, 3, 7], "diminished": [0, 3, 6]}[quality]
    if extension == "sus4":
        if inversion:
            raise ValueError("sus4には第三音がないため /3 を使えません")
        intervals = [0, 5, 7]
        quality = "sus4"
    elif extension:
        intervals = intervals + [{"7": 10, "maj7": 11, "add9": 14}[extension]]
    pitches = [root + interval for interval in intervals]
    if inversion:
        pitches = sorted(pitches[1:] + [root + 12])
    if any(pitch < 0 or pitch > 127 for pitch in pitches):
        raise ValueError(f"コード {token!r} の構成音がMIDIの範囲（0〜127）を超えています")
    return dict(token=token, degree=degree, accidental=(accidental == "#") - (accidental == "b"),
                quality=quality, extension=extension, inversion=int(bool(inversion)), borrowed=borrowed,
                role=role, pitches=pitches, root=root, bass=pitches[0])


def _bar_beats(meter):
    match = re.fullmatch(r"([1-9]\d*)/([1-9]\d*)", meter) if isinstance(meter, str) else None
    if not match:
        raise ValueError("[harmony] 拍子 meter: 正の整数による拍子を指定してください")
    numerator, denominator = map(int, match.groups())
    if denominator & (denominator - 1):
        raise ValueError("[harmony] 拍子 meter: 分母は2の累乗で指定してください")
    beats = numerator * 4 / denominator
    if not math.isfinite(beats) or beats <= 0:
        raise ValueError("[harmony] 拍子 meter: 拍数が範囲外です")
    return beats


def compile_progression(song, occurrences, *, base_octave=3):
    """展開済みoccurrencesに従って時刻付き和音dictのリストを返す。

    occurrencesはname/source/occurrence/start_beat/start_bar/barsを持つ。
    sourceのsections定義を参照し、ASCIIのA'もsource=Aとして再利用する。
    各小節内の空白区切りコードへ四分音符単位の拍数を等分する。
    parse_roman_chordの全項目にbeat,duration,section(出現名),source,
    bar(展開後1始まり)を追加する。入力は変更せず音源も読み込まない。
    """
    if not isinstance(song, dict):
        raise ValueError("[harmony] 曲: オブジェクトを指定してください")
    key = song.get("key")
    try:
        parse_key(key)
        degree_to_midi("1", key, base_octave=base_octave)
    except ValueError as exc:
        raise ValueError(f"[harmony] 調 key / 基準オクターブ: {exc}") from exc
    bar_beats = _bar_beats(song.get("meter"))
    sections = song.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("[harmony] セクション sections: オブジェクトを指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError("[harmony] 展開構造 occurrences: 空でないリストを指定してください")
    result = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError("[harmony] 展開構造 occurrences: 各要素はオブジェクトで指定してください")
        name, source = occurrence.get("name"), occurrence.get("source")
        start_bar, start_beat, bars = (occurrence.get(field) for field in ("start_bar", "start_beat", "bars"))
        location = f"[harmony] セクション {name!r} / 素材 {source!r}"
        if not isinstance(name, str) or not name or not isinstance(source, str) or not source:
            raise ValueError(f"{location}: name/sourceは空でない文字列で指定してください")
        if type(start_bar) is not int or start_bar < 1 or type(bars) is not int or bars < 1:
            raise ValueError(f"{location}: start_bar/barsは正の整数で指定してください")
        if (type(start_beat) not in (int, float) or not math.isfinite(start_beat) or start_beat < 0):
            raise ValueError(f"{location}: start_beatは0以上の有限数で指定してください")
        section = sections.get(source)
        if not isinstance(section, dict):
            raise ValueError(f"{location}: 素材が定義されていません")
        if type(section.get("bars")) is not int or section["bars"] != bars:
            raise ValueError(f"[harmony] {start_bar}番目の小節: {location} のbarsが展開構造と一致しません")
        chords = section.get("chords")
        if not isinstance(chords, str):
            raise ValueError(f"[harmony] {start_bar}番目の小節: {location} のchordsは文字列で指定してください")
        chord_bars = chords.split("|")
        if len(chord_bars) != bars:
            error_bar = start_bar + min(len(chord_bars), bars) - 1
            raise ValueError(f"[harmony] {error_bar}番目の小節: {location} のコード小節数がbarsと一致しません")
        for index, chord_bar in enumerate(chord_bars):
            bar = start_bar + index
            tokens = chord_bar.split()
            if not tokens:
                raise ValueError(f"[harmony] {bar}番目の小節: {location} のコード小節が空です")
            duration = bar_beats / len(tokens)
            for token_index, token in enumerate(tokens):
                try:
                    chord = parse_roman_chord(token, key, base_octave=base_octave)
                except ValueError as exc:
                    raise ValueError(f"[harmony] {bar}番目の小節: {location}: {exc}") from exc
                result.append(dict(chord, beat=start_beat + index * bar_beats + token_index * duration,
                                   duration=duration, section=name, source=source, bar=bar))
    return result
