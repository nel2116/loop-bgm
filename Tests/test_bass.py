import copy
import math

import pytest

from bgm.bass import compile_bass
from bgm.harmony import compile_progression
from bgm.structure import expand_form


def fixture(chords="I", meter="4/4", key="C major", form=None):
    song = {"key": key, "meter": meter, "form": form or ["A"],
            "sections": {"A": {"bars": len(chords.split("|")), "chords": chords}}}
    occurrences = expand_form(song)
    return song, occurrences, compile_progression(song, occurrences)


def bass(data, style="root_whole", **kwargs):
    return compile_bass({"name": "low", "role": "bass", "style": style, **kwargs}, *data)


def test_whole_progression():
    assert bass(fixture("I | vi | IV | V")) == [
        (0, [36], 4, 90), (4, [45], 4, 90), (8, [41], 4, 90), (12, [43], 4, 90)]


@pytest.mark.parametrize("style,times,pitches,durations,velocities", [
    ("root_whole", [0, 2], [38, 43], [2, 2], [90, 90]),
    ("root_quarter", [0, 1, 2, 3], [38, 38, 43, 43], [.9] * 4, [90, 72, 90, 72]),
    ("root_fifth", [0, 2], [38, 43], [1.8, 1.8], [90, 90]),
])
def test_two_chords_boundary_root_priority(style, times, pitches, durations, velocities):
    events = bass(fixture("ii V"), style)
    assert [e[0] for e in events] == times
    assert [e[1][0] for e in events] == pitches
    assert [e[2] for e in events] == pytest.approx(durations)
    assert [e[3] for e in events] == velocities


@pytest.mark.parametrize("meter,style,times,pitches,durations,velocities", [
    ("4/4", "root_fifth", [0, 2], [36, 43], [1.8, 1.8], [90, 90]),
    ("3/4", "root_whole", [0], [36], [3], [90]),
    ("3/4", "root_quarter", [0, 1, 2], [36] * 3, [.9] * 3, [90, 72, 72]),
    ("3/4", "root_fifth", [0, 2], [36, 43], [1.8, .9], [90, 72]),
    ("6/8", "root_whole", [0], [36], [3], [90]),
    ("6/8", "root_quarter", [0, 1, 2], [36] * 3, [.9] * 3, [90, 72, 72]),
    ("6/8", "root_fifth", [0, 1.5], [36, 43], [1.35] * 2, [90, 90]),
])
def test_meter_schedules(meter, style, times, pitches, durations, velocities):
    events = bass(fixture(meter=meter), style)
    assert [e[0] for e in events] == times
    assert [e[1][0] for e in events] == pitches
    assert [e[2] for e in events] == pytest.approx(durations)
    assert [e[3] for e in events] == velocities


@pytest.mark.parametrize("style", ["root_whole", "root_quarter", "root_fifth"])
@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_never_sustain_old_chord_and_union_articulation(style, meter):
    data = fixture("ii V I", meter)
    events = bass(data, style)
    chords = data[2]
    end = 4 if meter == "4/4" else 3
    for i, (beat, _, duration, _) in enumerate(events):
        chord = next(c for c in reversed(chords) if c["beat"] <= beat)
        assert beat + duration <= chord["beat"] + chord["duration"] + 1e-9
        next_beat = events[i + 1][0] if i + 1 < len(events) else end
        assert duration == pytest.approx((next_beat - beat) * (1 if style == "root_whole" else .9))
    for chord in chords:
        event = next(e for e in events if math.isclose(e[0], chord["beat"]))
        assert event[1] == [chord["root"] - 12]


def test_six_eight_midbar_and_accents():
    assert bass(fixture("ii V", "6/8"), "root_whole") == [(0, [38], 1.5, 90), (1.5, [43], 1.5, 90)]
    assert bass(fixture("ii V", "6/8"), "root_fifth") == [(0, [38], 1.35, 90), (1.5, [43], 1.35, 90)]
    events = bass(fixture("ii V", "6/8"), "root_quarter")
    assert [e[0] for e in events] == [0, 1, 1.5, 2]
    assert [e[2] for e in events] == pytest.approx([.9, .45, .45, .9])
    assert [e[3] for e in events] == [90, 72, 90, 72]


@pytest.mark.parametrize("key,token,root,fifth", [
    ("C major", "I/3", 36, 43), ("C minor", "I/3", 36, 43),
    ("C major", "vii°/3", 47, 53), ("C minor", "ii°7/3", 38, 44),
    ("C major", "bVII", 46, 53), ("C minor", "bVII", 46, 53),
    ("C major", "iv", 41, 48), ("C minor", "IV", 41, 48),
    ("A minor", "I", 45, 52), ("C major", "vii°sus4", 47, 54),
])
def test_precompiled_root_quality_inversions_and_borrowing(key, token, root, fifth):
    data = fixture(token, key=key)
    assert [e[1] for e in bass(data, "root_fifth")] == [[root], [fifth]]
    assert bass(data)[0][1] == [root]
    assert all(e[1] == [root] for e in bass(data, "root_quarter"))


def test_occurrence_selection_and_immutable_determinism():
    data = fixture("I | V", form=["A", "A'", "A"])
    before = copy.deepcopy(data)
    part = {"role": "bass", "style": "root_fifth", "sections": ["A'"], "octave": 1, "transpose": 2}
    saved = copy.deepcopy(part)
    events = compile_bass(part, *data)
    assert [e[0] for e in events] == [8, 10, 12, 14]
    assert [e[1] for e in events] == [[50], [57], [57], [64]]
    assert events == compile_bass(part, *data)
    assert data == before and part == saved
    assert [e[0] for e in bass(data, sections=["A"])] == [0, 4, 16, 20]
    assert bass(data, sections=[]) == []


@pytest.mark.parametrize("octave,transpose,note_range,expected", [
    (1, 2, (0, 127), 50), (1, 2, (36, 48), 38),
    (-4, -1, (0, 127), 11), (1000000, 5, (40, 51), 41),
    (0, 0, (37, 60), 48), (0, 0, (0, 35), 24),
])
def test_octave_then_transpose_then_range(octave, transpose, note_range, expected):
    events = compile_bass({"role": "bass", "style": "root_whole", "octave": octave, "transpose": transpose},
                          *fixture(), note_range=note_range)
    assert events[0][1] == [expected]


def test_impossible_range_is_positioned():
    with pytest.raises(ValueError, match=r"\[low\] 2番目の小節:.*オクターブ"):
        compile_bass({"name": "low", "role": "bass", "style": "root_whole"}, *fixture("I | V"), note_range=(36, 36))


@pytest.mark.parametrize("field,value", [
    ("bars", []), ("bars", ""), ("phrases", {}), ("phrases", ""), ("grid", None), ("groove", None),
    ("role", "chords"), ("role", None), ("type", "drums"), ("style", "walking"), ("style", []),
    ("octave", True), ("octave", 1.0), ("transpose", False), ("transpose", "2"),
    ("velocity", True), ("velocity", float("nan")), ("velocity", float("inf")),
    ("velocity", 0), ("velocity", 128), ("sections", ["B"]), ("sections", None), ("sections", "A"),
])
def test_invalid_part_values(field, value):
    with pytest.raises(ValueError, match=r"\[low\] 1番目の小節:"):
        bass(fixture(), **{field: value})


@pytest.mark.parametrize("note_range", [None, (), (0,), (0, 128), (True, 127), (2, 1), (0.0, 127), "0,127"])
def test_invalid_range(note_range):
    with pytest.raises(ValueError, match="note_range"):
        compile_bass({"role": "bass", "style": "root_whole"}, *fixture(), note_range=note_range)


@pytest.mark.parametrize("meter", ["2/4", "7/8", None, [], True])
def test_unsupported_meter(meter):
    data = fixture()
    data[0]["meter"] = meter
    with pytest.raises(ValueError, match="meter"):
        bass(data)


@pytest.mark.parametrize("field,value", [
    ("root", True), ("root", 128), ("root", 48.0), ("quality", "other"),
    ("beat", float("nan")), ("duration", float("inf")), ("duration", 0),
    ("duration", True), ("bar", False), ("bar", 2), ("section", "B"), ("source", "B"),
])
def test_invalid_harmony_values(field, value):
    data = fixture()
    data[2][0][field] = value
    with pytest.raises(ValueError, match=r"\[low\] .*番目の小節:"):
        bass(data)


@pytest.mark.parametrize("change", ["missing", "overlap", "gap", "reverse", "short", "long"])
def test_invalid_harmony_coverage(change):
    data = fixture("ii V")
    if change == "missing":
        data[2].clear()
    elif change == "reverse":
        data[2].reverse()
    elif change in ("overlap", "gap"):
        data[2][1]["beat"] += -1 if change == "overlap" else 1
    else:
        data[2][-1]["duration"] += -1 if change == "short" else 1
    with pytest.raises(ValueError, match="1番目の小節"):
        bass(data)


@pytest.mark.parametrize("field,value", [("start_bar", True), ("bars", 0), ("start_beat", float("nan")),
                                         ("name", None), ("source", ""), ("start_beat", 1)])
def test_invalid_occurrences(field, value):
    data = fixture()
    data[1][0][field] = value
    with pytest.raises(ValueError, match="occurrences"):
        bass(data)


def test_velocity_rounding_and_clamping():
    assert [e[3] for e in bass(fixture(), "root_quarter", velocity=1)] == [1] * 4
    assert [e[3] for e in bass(fixture(), "root_quarter", velocity=126.5)] == [126, 101, 126, 101]


def test_same_chord_rearticulates_at_every_boundary():
    assert bass(fixture("I I | I")) == [(0, [36], 2, 90), (2, [36], 2, 90), (4, [36], 4, 90)]


def test_fifth_corrects_its_own_register():
    events = compile_bass({"role": "bass", "style": "root_fifth"}, *fixture(), note_range=(31, 36))
    with pytest.raises(ValueError, match="オクターブ"):
        compile_bass({"role": "bass", "style": "root_fifth"}, *fixture(), note_range=(36, 36))
    assert [e[1] for e in events] == [[36], [31]]


def test_huge_velocity_rejected_as_value_error():
    with pytest.raises(ValueError, match="velocity"):
        bass(fixture(), velocity=10 ** 1000)


def test_direct_api_defaults_role_and_type():
    assert compile_bass({"style": "root_whole"}, *fixture()) == [(0, [36], 4, 90)]


@pytest.mark.parametrize("field", ["beat", "duration"])
def test_huge_harmony_time_rejected(field):
    data = fixture()
    data[2][0][field] = 10 ** 1000
    with pytest.raises(ValueError, match="1番目の小節"):
        bass(data)
