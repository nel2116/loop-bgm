import re

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE = re.compile(r"^([A-Ga-g])([#b]*)(-?\d+)$")
_KEY = re.compile(r"([A-Ga-g])([#b]?) (major|minor)")
_DEGREE = re.compile(r"([#b]?)([1-7])(,*|'*)")
_SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Chord symbols usable as  Cmaj7_3  (root C, octave 3)
CHORDS = {
    "": [0, 4, 7], "maj": [0, 4, 7], "m": [0, 3, 7], "min": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
    "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "m7b5": [0, 3, 6, 10], "dim7": [0, 3, 6, 9],
    "mmaj7": [0, 3, 7, 11], "9": [0, 4, 7, 10, 14], "maj9": [0, 4, 7, 11, 14], "m9": [0, 3, 7, 10, 14],
    "add9": [0, 4, 7, 14], "7sus4": [0, 5, 7, 10], "5": [0, 7],
}
_CHORD = re.compile(r"^([A-G][#b]?)(" + "|".join(sorted((re.escape(k) for k in CHORDS if k), key=len, reverse=True)) + r")?_(-?\d)$")


def note_to_midi(name: str) -> int:
    """'C4' -> 60, 'F#3' -> 54, 'Bb5' -> 82. C4 is middle C."""
    m = _NOTE.match(name.strip())
    if not m:
        raise ValueError(f"音名が読めません: {name!r}（例: C4, F#3, Bb5）")
    letter, acc, octave = m.groups()
    pc = _PC[letter.upper()] + acc.count("#") - acc.count("b")
    return 12 * (int(octave) + 1) + pc


def midi_to_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def parse_pitches(token: str):
    """'C4', 'C4+E4+G4' or a chord symbol 'Am7_3' -> list of MIDI numbers."""
    out = []
    for piece in token.split("+"):
        cm = _CHORD.match(piece)
        if cm and not _NOTE.match(piece):
            root = note_to_midi(cm.group(1) + cm.group(3))
            out += [root + i for i in CHORDS[cm.group(2) or ""]]
        else:
            out.append(note_to_midi(piece))
    return out


def midi_to_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def parse_key(key: str) -> tuple[int, str]:
    """主音のピッチクラス（0〜11）と major / minor（自然短調）を返す。"""
    match = _KEY.fullmatch(key.strip()) if isinstance(key, str) else None
    if match is None:
        raise ValueError(f"調が読めません: {key!r}（例: C major, A minor, Bb major）")
    letter, accidental, mode = match.groups()
    tonic = (_PC[letter.upper()] + (accidental == "#") - (accidental == "b")) % 12
    return tonic, mode


class PitchRangeError(ValueError):
    """音程がMIDIの範囲を超えたことを示す。part はパート名の文脈が付いた後に設定される。"""

    def __init__(self, message, part=None):
        super().__init__(message)
        self.part = part


def degree_to_midi(degree: str, key: str, *, base_octave: int, check_range: bool = True) -> int:
    """度数をMIDI音程へ変換する。基準は主音のピッチクラスの指定オクターブ。

    C major / base_octave=4 の1は60、5,は55、1'は72。
    異名同音の主音は同じ高さ（B# major と C major の1は同じ）になる。
    # / b は音階の音を半音上下し、同じオクターブ記号は複数付けられる。
    パートや小節の文脈は呼び出し元が ValueError に付け加える。
    check_range=False は変換前の途中値に使い、呼び出し元が変換後の音高を検査する。
    """
    tonic, mode = parse_key(key)
    if type(base_octave) is not int or not -1 <= base_octave <= 9:
        raise ValueError(f"基準オクターブは-1〜9の整数で指定してください: {base_octave!r}")
    match = _DEGREE.fullmatch(degree.strip()) if isinstance(degree, str) else None
    if match is None:
        raise ValueError(f"度数が読めません: {degree!r}（例: 1, #4, b7, 5, / 1'）")
    accidental, number, octave_marks = match.groups()
    midi = (12 * (base_octave + 1) + tonic + _SCALES[mode][int(number) - 1]
            + (accidental == "#") - (accidental == "b")
            + 12 * (octave_marks.count("'") - octave_marks.count(",")))
    if check_range and not 0 <= midi <= 127:
        raise PitchRangeError(f"度数 {degree!r} の音程がMIDIの範囲（0〜127）を超えています: {midi}")
    return midi
