"""小節非同期周期の数値・境界・入力検証。音声への統合はDで検証する。"""

import copy
import json
import os
import subprocess
import sys

import pytest

from bgm.harmony import compile_progression
from bgm.structure import expand_form
from bgm.variation_period import compile_period


def fixture(meter="4/4", chords="I", form=None, key="C major"):
    song = {"meter": meter, "key": key, "form": form or ["A"],
            "sections": {"A": {"bars": len(chords.split("|")), "chords": chords}, "B": {"bars": 1, "chords": "I"}}}
    return {"part": {"name": "分散", "role": "chords", "style": "arpeggio_up"}, "song": song,
            "occurrences": expand_form(song), "harmony": compile_progression(song, expand_form(song)), "period_beats": 3}


def test_true_three_beats_over_four_and_original_metadata():
    args = fixture(chords="I | I | I")
    result = compile_period(**args)
    assert result["events"] == [(float(t), [[48], [52], [55]][t % 3], .4, 108 if t % 4 in (0, 2) else 90) for t in range(12)]
    assert result["events"][4][1] == [52]
    assert result["events"][8][1] == [55]
    assert result["metadata"][4] == {"window": [4, 8], "ordinal": 0, "tones": [1], "harmony_index": 1,
                                      "occurrence": 0, "cycle": 1, "slot": 1}


@pytest.mark.parametrize("meter,accents", [("3/4", [0, 3]), ("6/8", [0, 1.5, 3, 4.5])])
def test_three_quarter_beats_and_compound_meter_accents(meter, accents):
    args = fixture(meter, chords="I | I")
    args["period_beats"] = 1.5
    assert compile_period(**args)["events"] == [
        (t / 2, [[48], [52], [55]][t % 3], .4, 108 if t / 2 in accents else 90) for t in range(12)]


@pytest.mark.parametrize("meter", ["3/4", "6/8"])
def test_four_beat_cycle_is_async_in_three_beat_meters(meter):
    args = fixture(meter, chords="I | I")
    args["period_beats"] = 4
    result = compile_period(**args)
    assert [e[0] for e in result["events"]] == [0, 4 / 3, 8 / 3, 4, 16 / 3]
    assert [e[1] for e in result["events"]] == [[48], [52], [55], [48], [52]]
    assert result["events"][2][2] == 3 - 8 / 3
    assert result["metadata"][2]["window"] == [0, 3]


def test_inversion_extension_and_full_voicing_reference():
    args = fixture(chords="Iadd9/3")
    result = compile_period(**args)
    assert args["harmony"][0]["root"] == 48
    assert args["harmony"][0]["pitches"] == [52, 55, 60, 62]
    assert [e[0] for e in result["events"]] == [0, .75, 1.5, 2.25, 3, 3.75]
    assert [e[1] for e in result["events"]] == [[52], [55], [60], [62], [52], [55]]
    assert [m["tones"] for m in result["metadata"]] == [[0], [1], [2], [3], [0], [1]]
    assert result["events"][-1][2] == .25


def variable_harmony(boundary=1.4):
    args = fixture()
    first = dict(args["harmony"][0], duration=boundary)
    second = dict(first, beat=boundary, duration=2.6 - boundary, pitches=[55, 59, 62, 65])
    third = dict(first, beat=2.6, duration=1.4)
    args["harmony"] = [first, second, third]
    return args


@pytest.mark.parametrize("boundary", [1.4, 1.5])
def test_current_harmony_changes_density_without_boundary_retrigger(boundary):
    result = compile_period(**variable_harmony(boundary))
    assert [e[0] for e in result["events"]] == [0, 1, 1.5, 2.25, 3]
    assert [e[1] for e in result["events"]] == [[48], [52], [62], [65], [48]]
    assert result["events"][1][2] == min(.4, boundary - 1)
    assert result["events"][3][2] == 2.6 - 2.25
    assert [m["harmony_index"] for m in result["metadata"]] == [0, 0, 1, 1, 2]
    assert [m["slot"] for m in result["metadata"]] == [0, 1, 2, 3, 0]


def test_fractional_harmony_without_new_attack_or_phase_reset():
    args = fixture(chords="I V I")
    result = compile_period(**args)
    assert result["events"] == [(0, [48], .4, 108), (1, [52], 4 / 3 - 1, 90), (2, [62], .4, 108), (3, [48], .4, 90)]


@pytest.mark.parametrize("boundary", [1 / 3, 2 / 3, 5 / 3, 7 / 3])
def test_rounded_fractional_candidate_belongs_to_new_harmony_once(boundary):
    args = fixture()
    args["period_beats"] = 1
    args["harmony"] = [dict(args["harmony"][0], duration=boundary),
                       dict(args["harmony"][0], beat=boundary, duration=4 - boundary, pitches=[60, 64, 67])]
    result = compile_period(**args)
    assert [e[0] for e in result["events"]].count(boundary) == 1
    index = next(i for i, e in enumerate(result["events"]) if e[0] == boundary)
    assert result["metadata"][index]["harmony_index"] == 1


def test_repeated_exact_occurrences_and_gap_do_not_reset_phase():
    args = fixture(form=["A", "B", "A", "A'"])
    args["part"]["sections"] = ["A"]
    result = compile_period(**args)
    assert [e[0] for e in result["events"]] == [0, 1, 2, 3, 8, 9, 10, 11]
    assert [e[1] for e in result["events"]][4:] == [[55], [48], [52], [55]]
    assert [m["occurrence"] for m in result["metadata"]] == [0] * 4 + [2] * 4
    assert compile_period(**args, section="A'") == {"events": [], "metadata": []}
    del args["part"]["sections"]
    primed = compile_period(**args, section="A'")
    assert [e[0] for e in primed["events"]] == [12, 13, 14, 15]
    assert [e[1] for e in primed["events"]] == [[48], [52], [55], [48]]


@pytest.mark.parametrize("period", [.6, 2.5, 100, 1e308])
def test_arbitrary_positive_period_and_song_end(period):
    args = fixture()
    args["period_beats"] = period
    result = compile_period(**args)
    assert result["events"][0][0] == 0
    assert all(0 <= t < 4 and 0 < d <= .4 and d <= period / 3 for t, _, d, _ in result["events"])
    assert all(t + d <= 4 for t, _, d, _ in result["events"])
    if period == .6:
        assert [e[0] for e in result["events"]][:6] == [0, .19999999999999998, .39999999999999997, .6, .7999999999999999, 1]


def test_large_representable_timing_does_not_overflow_spacing_validation():
    args = fixture()
    args["period_beats"] = 1.7e308
    args["occurrences"][0]["bars"] = 10**307
    args["harmony"][0].update(duration=4 * 10**307, pitches=[48])
    assert compile_period(**args)["events"] == [(0, [48], .4, 108)]


@pytest.mark.parametrize("velocity,expected", [(1, 1), (89.5, 107), (110, 127), (127, 127)])
def test_velocity_rounds_and_clamps_once(velocity, expected):
    args = fixture()
    args["part"]["velocity"] = velocity
    result = compile_period(**args)
    assert result["events"][0][3] == expected
    assert result["events"][1][3] == round(velocity)


def test_noop_still_validates_settings_and_unselected_material():
    args = fixture(form=["A", "A'"])
    args["part"]["sections"] = []
    assert compile_period(**args) == {"events": [], "metadata": []}
    args["harmony"][-1]["pitches"] = []
    with pytest.raises(ValueError, match=r"\[分散\] 2番目の小節"):
        compile_period(**args)


@pytest.mark.parametrize("period", [None, True, False, 0, -1, "3", float("nan"), float("inf"), -float("inf"), 10**400, 5e-324])
def test_invalid_or_unrepresentable_period(period):
    args = fixture()
    args["period_beats"] = period
    with pytest.raises(ValueError, match=r"\[分散\] 1番目の小節: .*period"):
        compile_period(**args)


@pytest.mark.parametrize("field,value", [
    ("role", "bass"), ("type", "drums"), ("type", None), ("style", "broken"), ("style", None),
    ("sections", None), ("sections", "A"), ("sections", ["Z"]), ("sections", ["A", "A"]), ("sections", [[]]),
    ("velocity", 0), ("velocity", True), ("velocity", float("nan")),
] + [(field, value) for field in ("bars", "phrases", "grid", "copy", "accent", "source", "groove", "kit", "voices")
     for value in (None, [], "")])
def test_invalid_part_fields_and_conflicts_by_presence(field, value):
    args = fixture()
    args["part"][field] = value
    with pytest.raises(ValueError, match=r"\[分散\] 1番目の小節"):
        compile_period(**args)


@pytest.mark.parametrize("section", ["", "Z", [], True, 3])
def test_invalid_exact_section(section):
    with pytest.raises(ValueError, match="section"):
        compile_period(**fixture(), section=section)


@pytest.mark.parametrize("target", ["part", "song", "occurrences", "harmony"])
@pytest.mark.parametrize("value", [None, [], "bad", 1])
def test_malformed_top_level(target, value):
    args = fixture()
    args[target] = value
    with pytest.raises(ValueError, match="番目の小節"):
        compile_period(**args)


@pytest.mark.parametrize("field,value", [
    ("beat", -1), ("beat", float("nan")), ("duration", 0), ("duration", 10**400),
    ("duration", .1), ("section", "B"), ("source", "B"), ("bar", True),
    ("pitches", []), ("pitches", [True]), ("pitches", [128]), ("pitches", "C"),
])
def test_malformed_harmony(field, value):
    args = fixture()
    args["harmony"][0][field] = value
    with pytest.raises(ValueError, match="番目の小節"):
        compile_period(**args)


def test_invalid_duration_reports_unfolded_global_bar():
    args = fixture(form=["A", "A'"])
    args["harmony"][1]["duration"] = 0
    with pytest.raises(ValueError, match=r"\[分散\] 2番目の小節"):
        compile_period(**args)


@pytest.mark.parametrize("field,value", [
    ("start_beat", 1), ("start_bar", 0), ("bars", 0), ("bars", 10**400),
    ("occurrence", True), ("occurrence", 1), ("name", ""), ("source", None),
])
def test_malformed_occurrences(field, value):
    args = fixture()
    args["occurrences"][0][field] = value
    with pytest.raises(ValueError, match="番目の小節"):
        compile_period(**args)


def test_unordered_harmony_missing_occurrence_and_unknown_meter():
    args = fixture(form=["A", "A'"])
    for field, value in [("harmony", args["harmony"][::-1]), ("harmony", args["harmony"][:1]),
                         ("harmony", [None]), ("occurrences", [None])]:
        with pytest.raises(ValueError):
            compile_period(**dict(args, **{field: value}))
    args["song"]["meter"] = "5/4"
    with pytest.raises(ValueError, match="meter"):
        compile_period(**args)


def test_pretransform_purity_independence_and_no_double_dsp():
    args = fixture(chords="Iadd9/3 | V7")
    original = copy.deepcopy(args)
    expected = compile_period(**args)
    assert args == original
    for field in ("octave", "transpose", "gate", "strum", "humanize", "volume", "pan", "instrument"):
        assert compile_period(**dict(args, part=dict(args["part"], **{field: 3}))) == expected
    args["song"].update(swing=.6, swing_unit=.5, id="unrelated", parts=[{"name": "other"}])
    assert compile_period(**args) == expected
    result = compile_period(**args)
    result["events"][0][1].append(127)
    result["metadata"][0]["window"][0] = 999
    assert compile_period(**args) == expected
    assert original["harmony"][0]["pitches"] == [52, 55, 60, 62]


def test_separate_process_determinism_without_audio_or_sibling_imports():
    code = '''
import json, sys
from bgm.variation_period import compile_period
from bgm.harmony import compile_progression
from bgm.structure import expand_form
song = {"meter":"4/4","key":"C major","form":["A"],"sections":{"A":{"bars":1,"chords":"I"}}}
occ = expand_form(song)
print(json.dumps(compile_period({"role":"chords","style":"arpeggio_up"}, song, occ,
                               compile_progression(song, occ), period_beats=3)))
assert not any(n in sys.modules for n in ("bgm.render", "bgm.sampler", "bgm.synth", "bgm.instruments",
                                         "bgm.variation", "bgm.variation_fill", "numpy", "soundfile"))
'''
    outputs = [subprocess.run([sys.executable, "-c", code], env=dict(os.environ, PYTHONHASHSEED=str(seed)),
                              check=True, capture_output=True, text=True).stdout for seed in (1, 321)]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["events"] == [[0, [48], .4, 108], [1, [52], .4, 90], [2, [55], .4, 108], [3, [48], .4, 90]]
