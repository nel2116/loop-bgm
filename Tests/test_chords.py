"""コード伴奏の数値スケジュールと純粋な和声変換を検証する。"""

import copy
import json
import subprocess
import sys

import pytest

from bgm.chords import compile_chords
from bgm.harmony import compile_progression
from bgm.structure import expand_form


def fixture(meter="4/4", chords="I", form=None, key="C major"):
    song = {"meter": meter, "key": key, "form": form or ["A"], "sections": {"A": {"bars": len(chords.split("|")), "chords": chords}}}
    occurrences = expand_form(song)
    return song, occurrences, compile_progression(song, occurrences)


def compile_fixture(style="pad", *, meter="4/4", chords="I", form=None, key="C major", note_range=(0, 127), **fields):
    song, occurrences, harmony = fixture(meter, chords, form, key)
    return compile_chords({"name": "伴奏", "role": "chords", "style": style, **fields}, song, occurrences, harmony, note_range=note_range)


@pytest.mark.parametrize("meter,length,accents", [("4/4", 4, [0, 2]), ("3/4", 3, [0]), ("6/8", 3, [0, 1.5])])
@pytest.mark.parametrize("style", ["pad", "block", "offbeat"])
def test_exact_single_bar_schedule(meter, length, accents, style):
    events = compile_fixture(style, meter=meter)
    offset = 0.5 if style == "offbeat" else 0
    positions = [0] if style == "pad" else [i + offset for i in range(length)]
    durations = [length] if style == "pad" else [0.4 if style == "offbeat" else 0.8] * length
    assert [e[0] for e in events] == positions
    assert [e[1] for e in events] == [[48, 52, 55]] * len(positions)
    assert [e[2] for e in events] == pytest.approx(durations)
    assert [e[3] for e in events] == [108 if p in accents else 90 for p in positions]


@pytest.mark.parametrize("meter,style,positions,durations,velocities", [
    ("4/4", "pad", [0, 2], [2, 2], [108, 108]),
    ("4/4", "block", [0, 1, 2, 3], [0.8] * 4, [108, 90, 108, 90]),
    ("4/4", "offbeat", [0.5, 1.5, 2.5, 3.5], [0.4] * 4, [90] * 4),
    ("3/4", "pad", [0, 1.5], [1.5, 1.5], [108, 90]),
    ("3/4", "block", [0, 1, 2], [0.8, 0.5, 0.8], [108, 90, 90]),
    ("3/4", "offbeat", [0.5, 1.5, 2.5], [0.4] * 3, [90] * 3),
    ("6/8", "pad", [0, 1.5], [1.5, 1.5], [108, 108]),
    ("6/8", "block", [0, 1, 2], [0.8, 0.5, 0.8], [108, 90, 90]),
    ("6/8", "offbeat", [0.5, 1.5, 2.5], [0.4] * 3, [90, 108, 90]),
])
def test_midbar_ii_v(meter, style, positions, durations, velocities):
    events = compile_fixture(style, meter=meter, chords="ii V")
    boundary = 2 if meter == "4/4" else 1.5
    assert [e[0] for e in events] == positions
    assert [e[1] for e in events] == [[50, 53, 57] if p < boundary else [55, 59, 62] for p in positions]
    assert [e[2] for e in events] == pytest.approx(durations)
    assert [e[3] for e in events] == velocities
    assert all(p + d <= (boundary if p < boundary else 2 * boundary) for p, _, d, _ in events)


@pytest.mark.parametrize("style", ["pad", "block", "offbeat"])
def test_dense_changes_clip_without_reanchoring(style):
    events = compile_fixture(style, chords="I ii V")
    positions = {"pad": [0, 4 / 3, 8 / 3], "block": [0, 1, 2, 3], "offbeat": [0.5, 1.5, 2.5, 3.5]}[style]
    assert [e[0] for e in events] == positions
    for beat, _, duration, _ in events:
        end = next(boundary for boundary in (4 / 3, 8 / 3, 4) if boundary > beat)
        assert beat + duration <= end


@pytest.mark.parametrize("style", ["pad", "block", "offbeat"])
def test_occurrence_names_repetitions_global_grid_and_clipping(style):
    events = compile_fixture(style, meter="6/8", chords="ii V", form=["A", "A'", "A"], sections=["A"])
    assert all(0 <= beat < 3 or 6 <= beat < 9 for beat, _, _, _ in events)
    half = len(events) // 2
    assert [(beat + 6, pitches, duration, vel) for beat, pitches, duration, vel in events[:half]] == events[half:]
    primed = compile_fixture(style, meter="6/8", chords="ii V", form=["A", "A'", "A"], sections=["A'"])
    assert all(3 <= beat < 6 and beat + duration <= 6 for beat, _, duration, _ in primed)
    assert len(primed) == half
    assert compile_fixture(style, sections=[]) == []


@pytest.mark.parametrize("style", ["pad", "block", "offbeat"])
def test_excess_harmony_duration_clips_at_next_chord_occurrence_and_song(style):
    song, occurrences, harmony = fixture(chords="ii V", form=["A", "A'"])
    for chord in harmony:
        chord["duration"] = 100
    events = compile_chords({"role": "chords", "style": style}, song, occurrences, harmony)
    for beat, _, duration, _ in events:
        assert beat + duration <= next(end for end in (2, 4, 6, 8) if end > beat)


@pytest.mark.parametrize("key,token,pitches", [
    ("C major", "I7", [48, 52, 55, 58]),
    ("C major", "Imaj7", [48, 52, 55, 59]),
    ("C major", "Isus4", [48, 53, 55]),
    ("C major", "Iadd9", [48, 52, 55, 62]),
    ("C major", "I/3", [52, 55, 60]),
    ("C major", "I7/3", [52, 55, 58, 60]),
    ("C major", "Imaj7/3", [52, 55, 59, 60]),
    ("C major", "Iadd9/3", [52, 55, 60, 62]),
    ("C major", "bVII", [58, 62, 65]),
    ("C major", "iv", [53, 56, 60]),
    ("C minor", "I", [48, 51, 55]),
    ("C minor", "IV", [53, 56, 60]),
    ("C minor", "V", [55, 59, 62]),
    ("C minor", "v", [55, 58, 62]),
    ("C minor", "bVII", [58, 62, 65]),
    ("C minor", "Iadd9/3", [51, 55, 60, 62]),
])
@pytest.mark.parametrize("style", ["pad", "block", "offbeat"])
def test_exact_harmony_pitches_and_intervals(key, token, pitches, style):
    assert all(event[1] == pitches for event in compile_fixture(style, key=key, chords=token))


@pytest.mark.parametrize("octave,transpose,note_range,expected", [
    (0, 0, (60, 84), [64, 67, 72, 74]),
    (0, 0, (0, 50), [40, 43, 48, 50]),
    (1, 2, (0, 127), [66, 69, 74, 76]),
    (-1, -2, (0, 127), [38, 41, 46, 48]),
    (10, 0, (60, 84), [64, 67, 72, 74]),
])
def test_common_octave_range_and_relative_transpose(octave, transpose, note_range, expected):
    # 大幅な相対オクターブ指定でも、最も近い合法な共通シフトを使う。
    events = compile_fixture(chords="Iadd9/3", octave=octave, transpose=transpose, note_range=note_range)
    assert events[0][1] == expected
    assert all(note_range[0] <= pitch <= note_range[1] for pitch in expected)


def test_impossible_common_voicing_has_part_and_global_bar():
    with pytest.raises(ValueError, match=r"\[伴奏\] 2番目の小節.*転回形"):
        compile_fixture(chords="I | Iadd9", note_range=(48, 59))


@pytest.mark.parametrize("velocity,expected", [(1, [1, 1, 1, 1]), (127, [127] * 4), (90.5, [109, 90, 109, 90])])
def test_velocity_rounding_clamping(velocity, expected):
    assert [e[3] for e in compile_fixture("block", velocity=velocity)] == expected


@pytest.mark.parametrize("field,value", [
    ("style", "broken"), ("style", None), ("style", []), ("role", "bass"), ("type", "drums"), ("type", None),
    ("bars", []), ("bars", None), ("phrases", {}), ("grid", ""), ("groove", ""), ("groove", None),
    ("octave", True), ("octave", 1.0), ("transpose", False), ("transpose", 0.5),
    ("velocity", True), ("velocity", "90"), ("velocity", 0), ("velocity", 128),
    ("velocity", float("inf")), ("velocity", float("nan")),
    ("sections", None), ("sections", "A"), ("sections", ["B"]), ("sections", [True]), ("sections", [[]]),
])
def test_part_validation_including_empty_field_presence(field, value):
    with pytest.raises(ValueError, match=r"\[伴奏\]"):
        compile_fixture(**{field: value})


@pytest.mark.parametrize("meter", ["2/4", "5/4", "6/4", "7/8", None, True, []])
def test_unknown_meter_never_falls_back(meter):
    song, occurrences, harmony = fixture()
    song["meter"] = meter
    with pytest.raises(ValueError, match="meter"):
        compile_chords({"role": "chords", "style": "pad"}, song, occurrences, harmony)


@pytest.mark.parametrize("note_range", [(60, 59), (-1, 127), (0, 128), (True, 127), (0, 127.0), None, (), (0,), "0..127"])
def test_invalid_internal_range(note_range):
    with pytest.raises(ValueError, match="note_range"):
        compile_fixture(note_range=note_range)


@pytest.mark.parametrize("target,field,value", [
    ("occurrences", "start_beat", True), ("occurrences", "start_beat", float("inf")),
    ("occurrences", "bars", False), ("occurrences", "start_bar", 0), ("occurrences", "source", None),
    ("harmony", "beat", float("nan")), ("harmony", "duration", True), ("harmony", "duration", 0),
    ("harmony", "pitches", []), ("harmony", "pitches", [True]), ("harmony", "pitches", [128]),
    ("harmony", "pitches", [60.0]), ("harmony", "section", None), ("harmony", "bar", False),
])
def test_malformed_precompiled_data(target, field, value):
    song, occurrences, harmony = fixture()
    (occurrences if target == "occurrences" else harmony)[0][field] = value
    with pytest.raises(ValueError, match=r"\[chords\]"):
        compile_chords({"role": "chords", "style": "pad"}, song, occurrences, harmony)


def test_inputs_immutable_outputs_independent_and_deterministic():
    song, occurrences, harmony = fixture(chords="Iadd9/3 | ii V", form=["A", "A'"])
    part = {"role": "chords", "style": "block"}
    before = copy.deepcopy((part, song, occurrences, harmony))
    first = compile_chords(part, song, occurrences, harmony)
    assert first == compile_chords(part, song, occurrences, harmony)
    assert before == (part, song, occurrences, harmony)
    first[0][1].append(99)
    assert 99 not in first[1][1]
    assert before == (part, song, occurrences, harmony)


@pytest.mark.parametrize("target,value", [
    ("part", None), ("song", []), ("occurrences", []), ("occurrences", [None]),
    ("harmony", []), ("harmony", [None]),
])
def test_malformed_top_level_arguments(target, value):
    song, occurrences, harmony = fixture()
    args = {"part": {"role": "chords", "style": "pad"}, "song": song, "occurrences": occurrences, "harmony": harmony}
    args[target] = value
    with pytest.raises(ValueError, match=r"\[chords\]"):
        compile_chords(**args)


def test_ordering_and_huge_timing_are_rejected():
    song, occurrences, harmony = fixture(form=["A", "A"])
    part = {"role": "chords", "style": "pad"}
    with pytest.raises(ValueError, match="順序"):
        compile_chords(part, song, list(reversed(occurrences)), harmony)
    with pytest.raises(ValueError, match="順序"):
        compile_chords(part, song, occurrences, list(reversed(harmony)))
    occurrences[0]["bars"] = 10 ** 400
    with pytest.raises(ValueError, match="有限"):
        compile_chords(part, song, occurrences, harmony)


def test_separate_process_without_sound_source_or_renderer_imports():
    code = '''
import json, sys
from bgm.chords import compile_chords
from bgm.harmony import compile_progression
from bgm.structure import expand_form
song = {"meter":"6/8","key":"C major","form":["A"],"sections":{"A":{"bars":1,"chords":"ii V"}}}
occ = expand_form(song)
print(json.dumps(compile_chords({"role":"chords","style":"block"}, song, occ, compile_progression(song, occ))))
assert not any(name in sys.modules for name in ("bgm.render", "bgm.sampler", "bgm.synth", "bgm.instruments", "soundfile"))
'''
    outputs = [subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True).stdout for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == [[0, [50, 53, 57], 0.8, 108], [1, [50, 53, 57], 0.5, 90], [2, [55, 59, 62], 0.8, 90]]
