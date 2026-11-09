"""度数メロディの単独コンパイル契約。"""

from copy import deepcopy

import pytest

from bgm.melody import compile_melody


def compile_phrase(phrase, **options):
    part = {"name": "lead", "grid": "1/4", "phrases": {"A": phrase}}
    part.update(options)
    return compile_melody(part, {"key": "C major", "meter": "4/4"}, occurrences())


def occurrences(**options):
    occ = dict(name="A", source="A", occurrence=0, start_beat=8, start_bar=3, bars=1)
    occ.update(options)
    return [occ]


def test_degrees_accidentals_octaves_rest_and_accents():
    assert compile_phrase("#4 b7 5, 1'") == [
        (8, [66], 1, 90), (9, [70], 1, 90), (10, [55], 1, 90), (11, [72], 1, 90),
    ]
    assert compile_phrase("1> . 3< [1 3 5]>") == [
        (8, [60], 1, 108), (10, [64], 1, 72), (11, [60, 64, 67], 1, 108),
    ]


def test_key_switch_and_no_mutation():
    part = {"phrases": {"A": "3 . . ."}, "grid": "1/4"}
    song = {"key": "C major", "meter": "4/4"}
    occs = occurrences()
    original = deepcopy((part, song, occs))
    assert compile_melody(part, song, occs)[0][1] == [64]
    assert (part, song, occs) == original
    assert compile_melody(part, dict(song, key="C minor"), occs)[0][1] == [63]


def test_tie_crosses_bar_but_not_occurrence():
    part = {"name": "lead", "grid": "1/4", "phrases": {"A": "1 - - - | - . 3 -"}}
    assert compile_melody(part, {"key": "C major", "meter": "4/4"}, occurrences(bars=2)) == [
        (8, [60], 5, 90), (14, [64], 2, 90),
    ]
    part["phrases"]["B"] = "- . . ."
    with pytest.raises(ValueError, match=r"\[lead\] 5番目の小節.*直前"):
        compile_melody(part, {"key": "C major", "meter": "4/4"}, occurrences(bars=2) + occurrences(
            name="B", source="B", occurrence=1, start_bar=5, start_beat=16))


@pytest.mark.parametrize("phrase", [
    "- 1 2 3", ". - 2 3", "C4 1 2 3", "8 1 2 3", "1>< 1 2 3", "[] 1 2 3",
    "[1]2 1 2", "[1 3 1 2", "[1 .] 1 2 3", "1 2 3", "1 2 3 4 5", "", "1 2 3 4 | 1 2 3 4",
])
def test_invalid_phrase_has_part_and_global_bar(phrase):
    with pytest.raises(ValueError, match=r"\[lead\] [34]番目の小節:"):
        compile_phrase(phrase)


def test_source_lookup_and_occurrence_selection():
    part = {"grid": "1/4", "phrases": {"A": "1 . . .", "A'": "7 . . ."}, "sections": ["A'"]}
    song = {"key": "C major", "meter": "4/4"}
    occs = occurrences() + occurrences(name="A'", occurrence=1, start_beat=12, start_bar=4)
    assert compile_melody(part, song, occs) == [(12, [60], 1, 90)]
    part["sections"] = ["A"]
    assert compile_melody(part, song, occs) == [(8, [60], 1, 90)]
    part["sections"] = []
    part["phrases"] = {}
    assert compile_melody(part, song, occs) == []
    part.pop("sections")
    with pytest.raises(ValueError, match="3番目の小節"):
        compile_melody(part, song, occs)


@pytest.mark.parametrize("field,value", [
    ("grid", None), ("grid", "2/4"), ("phrases", []), ("sections", ["B"]), ("sections", "A"),
    ("octave", True), ("octave", 1.5), ("transpose", 0.5), ("velocity", float("nan")),
    ("velocity", float("inf")), ("velocity", 0), ("velocity", 128), ("velocity", True),
])
def test_invalid_fields(field, value):
    with pytest.raises(ValueError, match=rf"\[lead\] {field} の指定"):
        compile_phrase("1 2 3 4", **{field: value})


def test_octave_transpose_clamp_and_midi_bounds():
    assert compile_phrase("1> 1< . .", octave=1, transpose=2, velocity=127) == [
        (8, [74], 1, 127), (9, [74], 1, 102),
    ]
    assert compile_phrase("1< . . .", velocity=1)[0][3] == 1
    for options in ({"transpose": 100}, {"octave": -6}):
        with pytest.raises(ValueError, match="3番目の小節.*MIDI|3番目の小節.*オクターブ"):
            compile_phrase("1 . . .", **options)


def test_compound_meter_eighth_grid_and_base_octave():
    part = {"grid": "1/8", "phrases": {"A": "1 2 3 4 5 6"}}
    events = compile_melody(part, {"key": "A minor", "meter": "6/8"}, occurrences(), base_octave=3)
    assert events[0] == (8, [57], 0.5, 90)
    assert events[-1] == (10.5, [65], 0.5, 90)
    part["grid"] = "1/7"
    with pytest.raises(ValueError, match="grid.*均等"):
        compile_melody(part, {"key": "A minor", "meter": "6/8"}, occurrences())


@pytest.mark.parametrize("song,field", [
    ({"key": "bad", "meter": "4/4"}, "key"), ({"key": "C major", "meter": "0/4"}, "meter"),
])
def test_invalid_song_fields(song, field):
    with pytest.raises(ValueError, match=field):
        compile_melody({"grid": "1/4", "phrases": {}}, song, occurrences())
