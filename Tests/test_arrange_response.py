"""合いの手と独立対旋律を混同せず、記譜区間から数値で検証する。"""

import copy
import json
import subprocess
import sys

import pytest

from bgm.arrange_response import compile_counter
from bgm.harmony import compile_progression
from bgm.melody import compile_melody
from bgm.structure import expand_form


def fixture(meter="4/4", *, form=None, chords="I"):
    song = {"key": "C major", "meter": meter, "form": form or ["A"],
            "sections": {"A": {"bars": 1, "chords": chords}, "B": {"bars": 1, "chords": "V"}},
            "parts": [{"name": "melody", "role": "melody", "bars": ["r:4"]}]}
    part = {"name": "response", "role": "arrange", "instrument": "kalimba", "accent": "counter", "source": "melody"}
    occurrences = expand_form(song)
    return part, song, occurrences, compile_progression(song, occurrences)


def run(data, events=None, **kwargs):
    return compile_counter(*data, [] if events is None else events, **kwargs)


@pytest.mark.parametrize("meter,velocities", [("4/4", [90, 72, 72, 72, 90, 72, 72, 72]),
                                             ("3/4", [90, 72, 72, 72, 72, 72]), ("6/8", [90, 72, 72, 90, 72, 72])])
def test_all_rest_exact_meters(meter, velocities):
    assert run(fixture(meter)) == [(i * .5, [60], .4, v) for i, v in enumerate(velocities)]


def test_union_chords_holds_adjacent_overlapping_unsorted():
    data = fixture()
    events = [(2, [67], 1, 90), (0, [60, 64], 1.5, 90), (1, [62], 1, 90), (3, [65], .25, 90)]
    assert run(data, events) == [(3.25, [60], .4, 72)]
    assert run(data, [(0, [60], 4, 90)]) == []


def test_real_phrase_hold_and_gate_not_occupancy():
    data = fixture()
    part, song, occurrences, _ = data
    source = song["parts"][0]
    source.pop("bars")
    source.update(grid="1/8", phrases={"A": "[1 3] - - . . 5 - ."}, gate=.1, strum=1, mute=True)
    events = compile_melody(source, song, occurrences)
    assert run(data, events) == [(1.5, [60], .4, 72), (2, [60], .4, 90), (3.5, [60], .4, 72)]
    part["gate"] = 2
    assert run(data, events) == [(1.5, [60], .4, 72), (2, [60], .4, 90), (3.5, [60], .4, 72)]


def test_partial_rests_short_fragments_and_end_no_wrap():
    assert run(fixture(), [(0, [60], .25, 90), (1.1, [60], 2.65, 90)]) == [(.25, [60], .4, 72)]
    assert run(fixture(), [(0, [60], 3.5, 90)]) == [(3.5, [60], .4, 72)]
    assert run(fixture(), [(0, [60], 3.75, 90)]) == []


def test_fractional_harmony_resets_and_root_ignores_inversion_extensions():
    result = run(fixture(chords="I/3 V7 bVIIadd9"))
    expected = [(0, 60), (.5, 60), (4 / 3, 67), (4 / 3 + .5, 67), (8 / 3, 70), (8 / 3 + .5, 70)]
    assert [(b, ps[0]) for b, ps, _, _ in result] == expected
    assert all(d == .4 for _, _, d, _ in result)


def test_fractional_exact_half_beat_gap_is_not_lost_to_rounding():
    start = 1 / 3
    assert run(fixture(), [(0, [60], start, 90), (start + .5, [60], 4 - start - .5, 90)]) == [
        (start, [60], .4, 72)]


@pytest.mark.parametrize("field,value", [("bar", True), ("beat", float("nan")), ("duration", 0),
                                        ("root", True), ("root", 128), ("pitches", []), ("pitches", [False]),
                                        ("section", None)])
def test_bad_harmony_even_empty_selection(field, value):
    data = fixture()
    data[0]["sections"] = []
    data[3][0][field] = value
    with pytest.raises(ValueError, match=r"\[response\] 1番目の小節"):
        run(data)


@pytest.mark.parametrize("field,value", [("start_bar", True), ("bars", 0), ("start_beat", 1), ("source", None)])
def test_bad_occurrence_even_empty_selection(field, value):
    data = fixture()
    data[0]["sections"] = []
    data[2][0][field] = value
    with pytest.raises(ValueError, match="occurrences"):
        run(data)


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_exact_selection_intersection_repeated_and_primed(meter):
    data = fixture(meter, form=["A", "B", "A", "A'"])
    part, song, _, _ = data
    bpb = 4 if meter == "4/4" else 3
    part["sections"] = ["A", "A'"]
    song["parts"][0]["sections"] = ["A"]
    assert [b for b, *_ in run(data)] == [base + i * .5 for base in (0, bpb * 2) for i in range(bpb * 2)]
    part["sections"] = ["B"]
    assert run(data) == []


def test_bar_boundary_reset_and_cross_bar_hold():
    data = fixture()
    data[1]["sections"]["A"].update(bars=2, chords="I | V")
    data = (*data[:2], expand_form(data[1]), compile_progression(data[1], expand_form(data[1])))
    assert run(data, [(0, [60], 4.25, 90)]) == [(4.25 + i * .5, [67], .4, 72) for i in range(7)]


def test_transforms_range_and_velocity():
    data = fixture()
    data[0].update(octave=1, transpose=2, velocity=100)
    assert run(data, note_range=(48, 64))[0] == (0, [62], .4, 100)
    assert run(data, note_range=(48, 64))[1] == (.5, [62], .4, 80)
    with pytest.raises(ValueError, match="音域"):
        run(data, note_range=(60, 61))


@pytest.mark.parametrize("field", ["copy", "style", "groove", "bars", "phrases", "grid", "kit", "voices"])
@pytest.mark.parametrize("value", [None, [], ""])
def test_notation_conflicts_by_presence(field, value):
    data = fixture()
    data[0].update(sections=[], **{field: value})
    with pytest.raises(ValueError, match=r"\[response\] 1番目の小節"):
        run(data)


@pytest.mark.parametrize("field,value", [("role", "melody"), ("type", "drums"), ("type", None), ("accent", None),
                                        ("instrument", None), ("source", "missing"), ("source", "response"), ("source", []),
                                        ("octave", True), ("transpose", .5), ("velocity", float("nan")),
                                        ("velocity", True), ("velocity", 0), ("sections", None), ("sections", ["missing"])])
def test_bad_settings_even_empty_selection(field, value):
    data = fixture()
    data[0]["sections"] = []
    data[0][field] = value
    with pytest.raises(ValueError, match=r"\[response\] 1番目の小節"):
        run(data)


@pytest.mark.parametrize("meter", ["5/4", None, [], 4])
def test_bad_meter_empty_selection(meter):
    data = fixture()
    data[1]["meter"] = meter
    data[0]["sections"] = []
    with pytest.raises(ValueError, match="meter"):
        run(data)


@pytest.mark.parametrize("change", [{"role": "arrange", "copy": "response"}, {"type": "drums"},
                                   {"source": "response"}, {"accent": "counter"}, {"grid": None}, {"sections": None}])
def test_reject_non_direct_source_and_invalid_selection(change):
    data = fixture()
    data[1]["parts"][0].update(change)
    with pytest.raises(ValueError):
        run(data)


def test_duplicate_reference_no_source_and_empty_event_distinction():
    data = fixture()
    assert len(run(data)) == 8
    data[1]["parts"].append(copy.deepcopy(data[1]["parts"][0]))
    with pytest.raises(ValueError, match="重複"):
        run(data)
    data[1]["parts"] = []
    with pytest.raises(ValueError, match="未定義"):
        run(data)


@pytest.mark.parametrize("event", [None, (0, [60], 1), (True, [60], 1, 90), (0, [], 1, 90),
                                  (0, [128], 1, 90), (0, [True], 1, 90), (0, [60], float("inf"), 90),
                                  (0, [60], 0, 90), (-1, [60], 1, 90), (4, [60], 1, 90), (0, [60], 1, True)])
def test_invalid_source_events(event):
    with pytest.raises(ValueError, match="参照音符"):
        run(fixture(), [event])


@pytest.mark.parametrize("note_range", [None, (True, 100), (50, 40), (0, 128), (0,), "range"])
def test_invalid_range_even_empty_selection(note_range):
    data = fixture()
    data[0]["sections"] = []
    with pytest.raises(ValueError, match="note_range"):
        run(data, note_range=note_range)


def test_partial_harmony_and_wrong_metadata_fail_with_global_bar():
    data = fixture(form=["A", "B", "A"])
    data[3].pop(1)
    with pytest.raises(ValueError, match="2番目の小節"):
        run(data)
    data = fixture()
    data[3][0]["duration"] = 3
    with pytest.raises(ValueError, match="過不足"):
        run(data)
    data[3][0]["duration"] = 4
    data[3][0]["source"] = "B"
    with pytest.raises(ValueError, match="セクション"):
        run(data)


def test_immutable_and_process_determinism():
    data = fixture(chords="iv V7")
    events = [(0, [60, 64], 1.25, 90)]
    before = copy.deepcopy((data, events))
    expected = run(data, events)
    assert (data, events) == before
    script = ("import json,sys; from bgm.arrange_response import compile_counter; "
              "print(json.dumps(compile_counter(*json.loads(sys.argv[1]))))")
    output = subprocess.check_output([sys.executable, "-c", script, json.dumps([*data, events])], text=True)
    assert json.loads(output) == json.loads(json.dumps(expected))
