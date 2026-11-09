import re

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE = re.compile(r"^([A-Ga-g])([#b]*)(-?\d+)$")
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
