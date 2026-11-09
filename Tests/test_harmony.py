import copy

import pytest

from bgm.harmony import compile_progression, parse_roman_chord
from bgm.structure import expand_form, meter_to_beats


@pytest.mark.parametrize("mode,roots,qualities", [
    ("major", [48, 50, 52, 53, 55, 57, 59],
     ["major", "minor", "minor", "major", "major", "minor", "diminished"]),
    ("minor", [48, 50, 51, 53, 55, 56, 58],
     ["minor", "diminished", "major", "minor", "major", "major", "major"]),
])
def test_all_roles_follow_mode(mode, roots, qualities):
    chords = [parse_roman_chord(token, f"C {mode}") for token in ("I", "ii", "iii", "IV", "V", "vi", "vii°")]
    assert [chord["root"] for chord in chords] == roots
    assert [chord["quality"] for chord in chords] == qualities
    assert [chord["role"] for chord in chords] == (
        ["I", "ii", "iii", "IV", "V", "vi", "vii°"] if mode == "major"
        else ["i", "ii°", "III", "iv", "V", "VI", "VII"])
    assert not any(chord["borrowed"] for chord in chords)


def test_mode_conversion_and_explicit_borrowing():
    assert parse_roman_chord("I", "C major")["pitches"] == [48, 52, 55]
    assert parse_roman_chord("I", "C minor")["pitches"] == [48, 51, 55]
    assert parse_roman_chord("IV", "C major")["pitches"] == [53, 57, 60]
    assert parse_roman_chord("IV", "C minor")["pitches"] == [53, 56, 60]
    for mode in ("major", "minor"):
        assert parse_roman_chord("V", f"C {mode}")["pitches"] == [55, 59, 62]
        borrowed = parse_roman_chord("bVII", f"C {mode}")
        assert borrowed["pitches"] == [58, 62, 65]
        assert borrowed["borrowed"] and borrowed["role"] == "bVII"
    assert parse_roman_chord("iv", "C major")["pitches"] == [53, 56, 60]
    assert parse_roman_chord("iv", "C major")["borrowed"]
    assert not parse_roman_chord("iv", "C minor")["borrowed"]
    assert parse_roman_chord("v", "C minor")["pitches"] == [55, 58, 62]


@pytest.mark.parametrize("token,role,quality", [
    ("i", "i", "minor"), ("ii°", "ii°", "diminished"), ("III", "III", "major"),
    ("iv", "iv", "minor"), ("v", "v", "minor"), ("VI", "VI", "major"), ("VII", "VII", "major"),
])
def test_minor_native_tokens(token, role, quality):
    chord = parse_roman_chord(token, "A minor")
    assert (chord["role"], chord["quality"]) == (role, quality)


@pytest.mark.parametrize("key,token,pitches", [
    ("C major", "I7", [48, 52, 55, 58]), ("C minor", "I7", [48, 51, 55, 58]),
    ("C major", "Imaj7", [48, 52, 55, 59]), ("C minor", "Imaj7", [48, 51, 55, 59]),
    ("C major", "Isus4", [48, 53, 55]), ("C minor", "Isus4", [48, 53, 55]),
    ("C major", "Iadd9", [48, 52, 55, 62]), ("C minor", "Iadd9", [48, 51, 55, 62]),
    ("C major", "vii°7", [59, 62, 65, 69]), ("C minor", "ii°7", [50, 53, 56, 60]),
    ("C minor", "ii°sus4", [50, 55, 57]), ("C major", "vii°sus4", [59, 64, 66]),
    ("C major", "ivadd9", [53, 56, 60, 67]), ("C minor", "bVIImaj7", [58, 62, 65, 69]),
    ("C major", "#iv", [54, 57, 61]),
])
def test_extensions_and_borrowing(key, token, pitches):
    assert parse_roman_chord(token, key)["pitches"] == pitches


@pytest.mark.parametrize("key,token,root,pitches", [
    ("C major", "I/3", 48, [52, 55, 60]), ("C minor", "I/3", 48, [51, 55, 60]),
    ("C major", "vii°7/3", 59, [62, 65, 69, 71]),
    ("C minor", "bVIIadd9/3", 58, [62, 65, 70, 72]),
    ("C major", "iv/3", 53, [56, 60, 65]),
])
def test_first_inversion(key, token, root, pitches):
    chord = parse_roman_chord(token, key)
    assert chord["root"] == root
    assert chord["bass"] == pitches[0]
    assert chord["pitches"] == pitches
    assert chord["inversion"] == 1


def test_metadata_and_tonic_octave():
    assert parse_roman_chord("I", "C minor") == dict(
        token="I", degree=1, accidental=0, quality="minor", extension=None,
        inversion=0, borrowed=False, role="i", pitches=[48, 51, 55], root=48, bass=48)
    assert parse_roman_chord("I", "A minor", base_octave=4)["root"] == 69
    assert parse_roman_chord("I", "B# major") == parse_roman_chord("I", "C major")
    assert parse_roman_chord("bVII", " C minor ")["accidental"] == -1
    sus = parse_roman_chord("Isus4", "C minor")
    assert sus["quality"] == sus["extension"] == "sus4"


@pytest.mark.parametrize("token", ["", " ", "H", "IIII", "Ii", "I°", "i", "III", "v", "VI", "VII",
                                       "I/5", "I7maj7", "I7sus4", "Isus4/3", "bIIIsus4/3", "bbVII", "I dim7", None, 4])
def test_invalid_tokens(token):
    with pytest.raises(ValueError, match="コード|第三音"):
        parse_roman_chord(token, "C major")


@pytest.mark.parametrize("key,octave", [("C dorian", 3), (None, 3), ("C major", True),
                                         ("C major", 10), ("B major", 9)])
def test_invalid_key_or_midi_range(key, octave):
    with pytest.raises(ValueError):
        parse_roman_chord("Iadd9/3", key, base_octave=octave)


def make_song(chords="I | vi | IV | V", bars=4, meter="4/4"):
    song = dict(key="C major", meter=meter, sections={"A": dict(bars=bars, chords=chords)})
    occurrences = [dict(name="A", source="A", occurrence=0, start_beat=0, start_bar=1, bars=bars)]
    return song, occurrences


def test_progression_and_repeated_source_do_not_mutate_inputs():
    song, occurrences = make_song()
    song["sections"]["A'"] = dict(bars=4, chords="V | V | V | V")
    occurrences.append(dict(name="A'", source="A", occurrence=1, start_beat=16, start_bar=5, bars=4))
    before = copy.deepcopy((song, occurrences))
    result = compile_progression(song, occurrences)
    assert (song, occurrences) == before
    assert [chord["beat"] for chord in result] == list(range(0, 32, 4))
    assert [chord["duration"] for chord in result] == [4] * 8
    assert [chord["root"] for chord in result] == [48, 57, 53, 55] * 2
    assert [chord["bar"] for chord in result] == list(range(1, 9))
    assert [chord["section"] for chord in result] == ["A"] * 4 + ["A'"] * 4
    assert all(chord["source"] == "A" for chord in result)
    result[0]["pitches"].append(99)
    assert result[4]["pitches"] == [48, 52, 55]


@pytest.mark.parametrize("meter,beats", [("4/4", 4), ("3/4", 3), ("6/8", 3), ("5/8", 2.5)])
def test_equal_time_split(meter, beats):
    song, occurrences = make_song("ii V | I I I", bars=2, meter=meter)
    occurrences[0].update(start_beat=7.5, start_bar=8)
    result = compile_progression(song, occurrences)
    assert [chord["beat"] for chord in result] == pytest.approx(
        [7.5, 7.5 + beats / 2, 7.5 + beats, 7.5 + beats * 4 / 3, 7.5 + beats * 5 / 3])
    assert [chord["duration"] for chord in result] == pytest.approx([beats / 2] * 2 + [beats / 3] * 3)
    assert [chord["bar"] for chord in result] == [8, 8, 9, 9, 9]


def test_compile_minor_extensions_inversions_and_borrowing():
    song, occurrences = make_song("Imaj7/3 | ii°7 V7 | bVIIadd9 | ivsus4")
    song["key"] = "C minor"
    result = compile_progression(song, occurrences)
    assert [chord["pitches"] for chord in result] == [
        [51, 55, 59, 60], [50, 53, 56, 60], [55, 59, 62, 65], [58, 62, 65, 72], [53, 58, 60]]
    assert [chord["beat"] for chord in result] == [0, 4, 6, 8, 12]


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8", "5/8", "2/2", "1/16", "11/32"])
def test_structure_connection_and_meter_agreement(meter):
    song, _ = make_song("I | V", bars=2, meter=meter)
    song["form"] = ["A", "A'", "A"]
    result = compile_progression(song, expand_form(song))
    beats = meter_to_beats(meter)
    assert [chord["beat"] for chord in result] == pytest.approx([index * beats for index in range(6)])
    assert [chord["bar"] for chord in result] == list(range(1, 7))
    assert [chord["section"] for chord in result] == ["A", "A", "A'", "A'", "A", "A"]


@pytest.mark.parametrize("meter", ["4/3", "0/4", "4/0", "04/4", "4/04", "4/４", " 4/4", None, 4])
def test_structure_and_harmony_reject_same_meters(meter):
    song, occurrences = make_song(meter=meter)
    with pytest.raises(ValueError):
        meter_to_beats(meter)
    with pytest.raises(ValueError, match=r"\[harmony\].*拍子"):
        compile_progression(song, occurrences)


@pytest.mark.parametrize("chords,bars,error_bar", [("I | X", 2, 6), ("I | ", 2, 6),
    ("", 1, 5), ("I || V", 3, 6), ("I", 2, 5), ("I | V | vi", 2, 6)])
def test_bad_bars_have_global_japanese_locations(chords, bars, error_bar):
    song, occurrences = make_song(chords, bars)
    occurrences[0].update(name="A'", start_bar=5, start_beat=16)
    with pytest.raises(ValueError, match=rf"\[harmony\] {error_bar}番目の小節:.*A'"):
        compile_progression(song, occurrences)


@pytest.mark.parametrize("field,value", [("key", "C weird"), ("meter", "4/3"), ("meter", "0/4"),
                                        ("meter", None), ("sections", []), ("sections", {})])
def test_invalid_song_structure(field, value):
    song, occurrences = make_song()
    song[field] = value
    with pytest.raises(ValueError, match=r"\[harmony\].*[ぁ-んァ-ヶ一-龯]"):
        compile_progression(song, occurrences)


@pytest.mark.parametrize("field,value", [("bars", True), ("bars", 3), ("chords", None)])
def test_section_mismatch(field, value):
    song, occurrences = make_song()
    song["sections"]["A"][field] = value
    with pytest.raises(ValueError, match=r"\[harmony\] 1番目の小節"):
        compile_progression(song, occurrences)


@pytest.mark.parametrize("field,value", [("start_bar", 0), ("bars", False), ("start_beat", float("nan")),
                                        ("start_beat", -1), ("name", []), ("source", "missing")])
def test_invalid_occurrence(field, value):
    song, occurrences = make_song()
    occurrences[0][field] = value
    with pytest.raises(ValueError, match=r"\[harmony\].*[ぁ-んァ-ヶ一-龯]"):
        compile_progression(song, occurrences)


@pytest.mark.parametrize("occurrences", [[], None, [None]])
def test_empty_or_invalid_occurrences(occurrences):
    song, _ = make_song()
    with pytest.raises(ValueError, match="展開構造"):
        compile_progression(song, occurrences)


def test_invalid_song_and_out_of_range_chord_location():
    with pytest.raises(ValueError, match="曲"):
        compile_progression(None, [])
    song, occurrences = make_song("Iadd9", bars=1)
    song["key"] = "B major"
    with pytest.raises(ValueError, match=r"\[harmony\] 1番目の小節:.*MIDI"):
        compile_progression(song, occurrences, base_octave=8)
