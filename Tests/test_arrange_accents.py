"""句頭と裏拍の確定した数値・入力境界を検証する。"""

import copy
import json
import os
import subprocess
import sys

import pytest

from bgm.arrange_accents import compile_offbeat_tick, compile_phrase_start
from bgm.harmony import compile_progression
from bgm.structure import expand_form


def fixture(meter="4/4", chords="I", form=None, bars=1):
    song = {"key": "C major", "meter": meter, "form": form or ["A"],
            "sections": {"A": {"bars": bars, "chords": chords}, "B": {"bars": bars, "chords": chords}}}
    occurrences = expand_form(song)
    return song, occurrences, compile_progression(song, occurrences)


def phrase(**fields):
    return {"name": "sparkle", "role": "arrange", "instrument": "kalimba", "accent": "phrase_start", **fields}


def tick(**fields):
    return {"name": "tick", "role": "arrange", "accent": "offbeat_tick", **fields}


@pytest.mark.parametrize("meter,offsets", [("4/4", [.5, 1.5, 2.5, 3.5]), ("3/4", [.5, 1.5, 2.5]), ("6/8", [.75, 2.25])])
def test_all_meters_reset_and_numeric_events(meter, offsets):
    song, occ, harmony = fixture(meter, "I | V", bars=2)
    beats = 4 if meter == "4/4" else 3
    assert compile_phrase_start(phrase(), song, occ, harmony) == [(0, [67], .5, 108)]
    assert compile_offbeat_tick(tick(), song, occ) == [(b + x, "hat", 76) for b in (0, beats) for x in offsets]


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
@pytest.mark.parametrize("selection,indices", [(None, [0, 1, 2, 3]), (["A"], [0, 2]), (["A'"], [3]), ([], [])])
def test_exact_occurrence_selection(meter, selection, indices):
    song, occ, harmony = fixture(meter, form=["A", "B", "A", "A'"])
    fields = {} if selection is None else {"sections": selection}
    beats = 4 if meter == "4/4" else 3
    assert compile_phrase_start(phrase(**fields), song, occ, harmony) == [(i * beats, [67], .5, 108) for i in indices]
    offsets = [.5, 1.5, 2.5, 3.5] if meter == "4/4" else [.75, 2.25] if meter == "6/8" else [.5, 1.5, 2.5]
    assert compile_offbeat_tick(tick(**fields), song, occ) == [(i * beats + x, "hat", 76) for i in indices for x in offsets]


@pytest.mark.parametrize("key,chord,pitch", [("C major", "I", 67), ("C minor", "I", 67), ("C major", "I/3", 72),
                                          ("C major", "Iadd9", 74), ("C major", "Imaj7", 71), ("C major", "V7/3", 79),
                                          ("C major", "iv", 72), ("C major", "bVII", 77), ("C minor", "bVII", 77)])
def test_actual_top_harmony_tone(key, chord, pitch):
    song, occ, _ = fixture(chords=chord)
    song["key"] = key
    assert compile_phrase_start(phrase(), song, occ, compile_progression(song, occ)) == [(0, [pitch], .5, 108)]


def test_fractional_harmony_does_not_invent_boundaries():
    song, occ, harmony = fixture(chords="I ii V | IV V I", bars=2)
    assert harmony[1]["beat"] == 4 / 3
    assert compile_phrase_start(phrase(), song, occ, harmony) == [(0, [67], .5, 108)]
    short = copy.deepcopy(harmony[:1])
    short[0]["duration"] = .125
    assert compile_phrase_start(phrase(gate=.01, swing=.4), song, occ, short) == [(0, [67], .125, 108)]


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_fractional_harmony_roundoff_is_not_overlap(meter):
    song, occ, harmony = fixture(meter, " ".join(["I"] * 9))
    beats = 4 if meter == "4/4" else 3
    assert compile_phrase_start(phrase(), song, occ, harmony) == [(0, [67], beats / 9, 108)]


def test_partial_harmony_selected_boundaries_and_song_end():
    song, occ, harmony = fixture(form=["A", "B", "A", "A'"])
    last = copy.deepcopy(harmony[-1:])
    last[0]["duration"] = .25
    assert compile_phrase_start(phrase(sections=["A'"]), song, occ, last) == [(12, [67], .25, 108)]
    assert compile_phrase_start(phrase(sections=[]), song, occ, []) == []
    with pytest.raises(ValueError, match=r"\[sparkle\] 1番目の小節.*句頭"):
        compile_phrase_start(phrase(sections=["A"]), song, occ, last)
    harmony[0]["beat"] = .25
    harmony[0]["duration"] -= .25
    with pytest.raises(ValueError, match="句頭"):
        compile_phrase_start(phrase(), song, occ, harmony)


@pytest.mark.parametrize("fields,note_range,pitch", [({}, (60, 72), 67), ({"octave": 1, "transpose": 2}, (0, 127), 81),
                                                   ({"octave": 1, "transpose": 2}, (60, 72), 69), ({}, (0, 60), 55),
                                                   ({}, (80, 100), 91), ({"octave": -1}, (0, 127), 55)])
def test_pitch_transform_and_range(fields, note_range, pitch):
    song, occ, harmony = fixture()
    assert compile_phrase_start(phrase(**fields), song, occ, harmony, note_range=note_range) == [(0, [pitch], .5, 108)]


def test_impossible_range_and_velocity_rounding():
    song, occ, harmony = fixture()
    with pytest.raises(ValueError, match="音域"):
        compile_phrase_start(phrase(), song, occ, harmony, note_range=(60, 60))
    assert compile_phrase_start(phrase(velocity=127), song, occ, harmony)[0][3] == 127
    assert compile_phrase_start(phrase(velocity=1), song, occ, harmony)[0][3] == 1
    assert compile_offbeat_tick(tick(velocity=90), song, occ)[0][2] == 72
    assert compile_offbeat_tick(tick(velocity=1), song, occ)[0][2] == 1
    assert compile_offbeat_tick(tick(velocity=100.625), song, occ)[0][2] == 80


@pytest.mark.parametrize("field", ["bars", "phrases", "grid", "style", "groove", "copy", "source"])
@pytest.mark.parametrize("value", [None, [], {}, ""])
@pytest.mark.parametrize("drum", [False, True])
def test_notation_conflicts_by_presence(field, value, drum):
    song, occ, harmony = fixture()
    part = (tick if drum else phrase)(sections=[], **{field: value})
    with pytest.raises(ValueError, match=r"\[(tick|sparkle)\] 1番目の小節"):
        compile_offbeat_tick(part, song, occ) if drum else compile_phrase_start(part, song, occ, harmony)


@pytest.mark.parametrize("fields", [{"role": None}, {"role": "melody"}, {"type": "drums"}, {"accent": None},
                                  {"instrument": None}, {"instrument": ""}, {"kit": None}, {"voices": {}},
                                  {"octave": True}, {"transpose": 1.5}, {"velocity": False}, {"velocity": float("nan")},
                                  {"velocity": float("inf")}, {"velocity": 0}, {"sections": None}, {"sections": ["Z"]}])
def test_phrase_invalid_even_empty_selection(fields):
    song, occ, harmony = fixture()
    with pytest.raises(ValueError, match=r"\[sparkle\] 1番目の小節"):
        compile_phrase_start(phrase(**{"sections": [], **fields}), song, occ, harmony)


@pytest.mark.parametrize("fields", [{"role": None}, {"type": "notes"}, {"accent": []}, {"instrument": None},
                                  {"kit": None}, {"kit": []}, {"kit": ["hihat"]}, {"voices": None},
                                  {"voices": {"fake": {}}}, {"voices": {"hat": []}}, {"voices": {"hat": {"pan": True}}},
                                  {"voices": {"hat": {"volume": float("inf")}}}, {"velocity": None}, {"sections": None}])
def test_tick_invalid_even_empty_selection(fields):
    song, occ, _ = fixture()
    with pytest.raises(ValueError, match=r"\[tick\] 1番目の小節"):
        compile_offbeat_tick(tick(**{"sections": [], **fields}), song, occ)


@pytest.mark.parametrize("meter", [None, [], "5/4", "7/8", True])
def test_unsupported_meter_even_empty(meter):
    song, occ, harmony = fixture()
    song["meter"] = meter
    with pytest.raises(ValueError, match="meter"):
        compile_phrase_start(phrase(sections=[]), song, occ, harmony)
    with pytest.raises(ValueError, match="meter"):
        compile_offbeat_tick(tick(sections=[]), song, occ)


@pytest.mark.parametrize("field,value", [("beat", float("nan")), ("duration", 0), ("pitches", []), ("pitches", [True]),
                                       ("section", "B"), ("source", "B"), ("bar", 2), ("duration", 5)])
def test_all_harmony_metadata_validated_even_empty(field, value):
    song, occ, harmony = fixture()
    harmony[0][field] = value
    with pytest.raises(ValueError, match=r"\[sparkle\].*番目の小節"):
        compile_phrase_start(phrase(sections=[]), song, occ, harmony)


def test_catalog_kit_and_voice_configuration():
    from bgm.instruments import PERCUSSION, SYNTH_DRUMS

    song, occ, _ = fixture()
    available = {**PERCUSSION, **SYNTH_DRUMS}
    expected = [(.5, "hat", 76), (1.5, "hat", 76), (2.5, "hat", 76), (3.5, "hat", 76)]
    assert compile_offbeat_tick(tick(kit=["tambourine", "hat"], voices={"hat": None, "tambourine": {"pan": 2}}),
                                song, occ, available_voices=available) == expected
    for available in ({"tambourine": {}}, ["hihat"], "hat", [None]):
        with pytest.raises(ValueError, match="available_voices"):
            compile_offbeat_tick(tick(sections=[]), song, occ, available_voices=available)


def test_swing_validated_but_not_applied_and_no_double_dsp():
    song, occ, harmony = fixture()
    song["swing"] = .6
    assert compile_offbeat_tick(tick(), song, occ)[0] == (.5, "hat", 76)
    assert compile_phrase_start(phrase(gate=.2, strum=.1, humanize=1), song, occ, harmony) == [(0, [67], .5, 108)]
    for fields in ({"swing": -1}, {"swing": 3}, {"swing": float("inf")}, {"swing_unit": 0}, {"swing_unit": True}):
        with pytest.raises(ValueError, match=r"\[tick\] 1番目の小節"):
            compile_offbeat_tick(tick(sections=[]), {**song, **fields}, occ)


@pytest.mark.parametrize("value", [None, [], [60], [True, 127], [70, 60], [-1, 127]])
def test_bad_range_even_empty(value):
    song, occ, harmony = fixture()
    with pytest.raises(ValueError, match="note_range"):
        compile_phrase_start(phrase(sections=[]), song, occ, harmony, note_range=value)


@pytest.mark.parametrize("field,value", [("start_beat", .25), ("start_bar", 2), ("bars", True), ("source", None)])
def test_bad_occurrences_even_empty(field, value):
    song, occ, harmony = fixture()
    occ[0][field] = value
    for part, compiler in ((phrase(sections=[]), compile_phrase_start), (tick(sections=[]), compile_offbeat_tick)):
        with pytest.raises(ValueError, match="occurrences"):
            compiler(part, song, occ, harmony) if compiler is compile_phrase_start else compiler(part, song, occ)


def test_pure_deterministic_across_processes_and_input_unchanged():
    song, occ, harmony = fixture("6/8", "Iadd9/3 V7 bVII", ["A", "B", "A", "A'"])
    part, drum = phrase(sections=["A", "A'"]), tick(kit=["hat"])
    inputs = (part, drum, song, occ, harmony)
    before = copy.deepcopy(inputs)
    notes = compile_phrase_start(part, song, occ, harmony)
    drums = compile_offbeat_tick(drum, song, occ)
    assert notes == [(0, [74], .5, 108), (6, [74], .5, 108), (9, [74], .5, 108)]
    code = ("import json,sys; from bgm.arrange_accents import compile_phrase_start,compile_offbeat_tick; "
            "p,d,s,o,h=json.load(sys.stdin); print(json.dumps([compile_phrase_start(p,s,o,h),compile_offbeat_tick(d,s,o)]))")
    for seed in ("1", "999"):
        result = subprocess.run([sys.executable, "-c", code], input=json.dumps(inputs), text=True, capture_output=True,
                                check=True, env={**os.environ, "PYTHONHASHSEED": seed})
        assert json.loads(result.stdout) == json.loads(json.dumps([notes, drums]))
    assert inputs == before
    notes[0][1][0] = 1
    assert inputs == before
