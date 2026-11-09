import pytest

from bgm.theory import degree_to_midi, note_to_midi, parse_key, parse_pitches


@pytest.mark.parametrize(("key", "expected"), [
    ("C major", [60, 62, 64, 65, 67, 69, 71]),
    ("C minor", [60, 62, 63, 65, 67, 68, 70]),
    ("A minor", [69, 71, 72, 74, 76, 77, 79]),
    ("D major", [62, 64, 66, 67, 69, 71, 73]),
])
def test_scales(key, expected):
    assert [degree_to_midi(str(n), key, base_octave=4) for n in range(1, 8)] == expected


@pytest.mark.parametrize(("first", "second", "tonic"), [
    ("C#", "Db", 1), ("F#", "Gb", 6), ("B#", "C", 0), ("Cb", "B", 11), ("E#", "F", 5),
])
@pytest.mark.parametrize("mode", ["major", "minor"])
def test_enharmonic_keys(first, second, tonic, mode):
    assert parse_key(f"{first} {mode}") == parse_key(f"{second} {mode}") == (tonic, mode)
    for degree in ("1", "3", "7", "#4", "b7", "5,", "1'"):
        assert degree_to_midi(degree, f"{first} {mode}", base_octave=4) == degree_to_midi(
            degree, f"{second} {mode}", base_octave=4)


@pytest.mark.parametrize(("degree", "expected"), [
    ("#4", 66), ("b7", 70), ("b1", 59), ("#7", 72),
    ("5,", 55), ("1'", 72), ("1,,", 36), ("1''", 84), ("#4,", 54), ("b7'", 82),
])
def test_accidentals_and_octaves(degree, expected):
    assert degree_to_midi(degree, "C major", base_octave=4) == expected


def test_minor_accidentals_are_relative_to_scale():
    assert degree_to_midi("#7", "A minor", base_octave=4) == 80
    assert degree_to_midi("b3", "C minor", base_octave=4) == 62


def test_whitespace_and_lowercase_tonic():
    assert parse_key(" c# minor ") == (1, "minor")
    assert degree_to_midi(" 3 ", " c major ", base_octave=4) == 64


@pytest.mark.parametrize(("degree", "octave", "expected"), [
    ("1", -1, 0), ("5", 9, 127), ("1,", 0, 0), ("5'", 8, 127),
])
def test_midi_boundaries(degree, octave, expected):
    assert degree_to_midi(degree, "C major", base_octave=octave) == expected


@pytest.mark.parametrize("key", [None, 1, [], {}, "", "H major", "C", "C dorian", "C harmonic minor",
                                      "C Major", "C## major", "C#b minor", "C major\njunk", "C4 major"])
def test_invalid_keys(key):
    with pytest.raises(ValueError, match="調が読めません"):
        parse_key(key)
    with pytest.raises(ValueError, match="調が読めません"):
        degree_to_midi("1", key, base_octave=4)


@pytest.mark.parametrize("degree", [None, 1, [], {}, "", "0", "8", "12", "１", "##4", "bb7", "#b4",
                                         "4#", "1,'", "1',", "1 ' ", "1\n2", "C4", "r", ".", "-"])
def test_invalid_degrees(degree):
    with pytest.raises(ValueError, match="度数が読めません"):
        degree_to_midi(degree, "C major", base_octave=4)


@pytest.mark.parametrize("octave", [None, True, False, 4.0, "4", [], {}, -2, 10])
def test_invalid_octaves(octave):
    with pytest.raises(ValueError, match="基準オクターブ"):
        degree_to_midi("1", "C major", base_octave=octave)


@pytest.mark.parametrize(("degree", "key", "octave"), [
    ("b1", "C major", -1), ("1,", "C major", -1), ("#5", "C major", 9),
    ("1", "B major", 9), ("1'", "C major", 9), ("1,,,,,,,,,,,,", "C major", 4),
])
def test_out_of_midi_range(degree, key, octave):
    with pytest.raises(ValueError, match="MIDIの範囲"):
        degree_to_midi(degree, key, base_octave=octave)


@pytest.mark.parametrize(("name", "expected"), [
    ("C4", 60), ("F#3", 54), ("Bb5", 82), ("B#3", 60), ("Cb4", 59),
    ("C##4", 62), (" c4 ", 60), ("C-2", -12), ("G#9", 128),
])
def test_legacy_absolute_notes(name, expected):
    assert note_to_midi(name) == expected


@pytest.mark.parametrize(("token", "expected"), [
    ("C4", [60]), ("C4+E4+G4", [60, 64, 67]),
    ("Am7_3", [57, 60, 64, 67]), ("Cmaj7_3", [48, 52, 55, 59]),
    ("Bb_3", [58, 62, 65]), ("C4+Am7_3", [60, 57, 60, 64, 67]),
])
def test_legacy_pitch_tokens(token, expected):
    assert parse_pitches(token) == expected


@pytest.mark.parametrize("token", ["1", "#4", "b7", "1'"])
def test_legacy_pitch_tokens_reject_degrees(token):
    with pytest.raises(ValueError, match="音名が読めません"):
        parse_pitches(token)
