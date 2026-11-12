"""コピーの数値イベントと参照グラフ契約を検証する。"""

import copy
import json
import subprocess
import sys

import pytest

from bgm.arrange_copy import compile_copy, reference_order, resolve_copy_instrument
from bgm.chords import compile_chords
from bgm.harmony import compile_progression
from bgm.structure import expand_form


def fixture(meter="4/4"):
    song = {"meter": meter, "key": "C major", "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": 1, "chords": "I"}, "B": {"bars": 1, "chords": "V"}}}
    return song, expand_form(song)


def part(**fields):
    return {"name": "重ね", "role": "arrange", "copy": "melody", **fields}


def run(events=None, *, meter="4/4", note_range=(0, 127), **fields):
    song, occurrences = fixture(meter)
    return compile_copy(part(**fields), song, occurrences, events if events is not None else [(0, [60, 64, 67], 1, 90)],
                        note_range=note_range)


@pytest.mark.parametrize("meter,beats", [("4/4", 4), ("3/4", 3), ("6/8", 3)])
def test_exact_selection_repeated_and_primed(meter, beats):
    events = [(i * beats + .25, [60, 67], beats, 83) for i in range(4)]
    assert run(events, meter=meter, sections=["A"], octave=1) == [
        (.25, [72, 79], beats - .25, 83), (2 * beats + .25, [72, 79], beats - .25, 83)]
    assert run(events, meter=meter, sections=["A'"]) == [(3 * beats + .25, [60, 67], beats - .25, 83)]
    assert run(events, meter=meter, sections=[]) == []


def test_no_reattack_or_harmony_split_and_song_end():
    events = [(3, [60], 9, 73), (4.25, [61], 8, 84), (15.75, [62], 3, 95)]
    assert run(events, sections=["B"]) == [(4.25, [61], 3.75, 84)]
    assert run(events)[-1] == (15.75, [62], .25, 95)
    assert run([(0, [60], 4, 90)]) == [(0, [60], 4, 90)]


def test_source_pitch_already_transformed_and_destination_dsp_not_baked_in():
    assert run([(1 / 3, [73, 77], 2 / 3, 106)], octave=-1, transpose=2, gate=.1, strum=.5,
               humanize=1, volume=-30, pan=1, mute=True) == [(1 / 3, [63, 67], 2 / 3, 106)]


@pytest.mark.parametrize("token", ["I/3", "V7/3", "Iadd9", "bVII", "iv"])
@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_full_harmony_pitches_common_octave_correction(token, meter):
    song, occurrences = fixture(meter)
    song["sections"]["A"]["chords"] = token
    harmony = compile_progression(song, occurrences)
    source = compile_chords({"name": "melody", "role": "chords", "style": "pad", "octave": 1}, song, occurrences, harmony)
    result = compile_copy(part(octave=2, transpose=1), song, occurrences, source, note_range=(48, 83))
    for old, new in zip(source, result, strict=True):
        assert old[0] == new[0] and old[2:] == new[2:]
        assert all(48 <= pitch <= 83 for pitch in new[1])
        assert [p - new[1][0] for p in new[1]] == [p - old[1][0] for p in old[1]]
        assert all((a - b) % 12 == 1 for a, b in zip(new[1], old[1], strict=True))


def test_numeric_range_correction_and_impossible_chord():
    assert run(note_range=(48, 67), octave=2) == [(0, [60, 64, 67], 1, 90)]
    with pytest.raises(ValueError, match=r"\[重ね\] 3番目の小節.*全構成音"):
        run([(8, [60, 84], 1, 90)], note_range=(60, 72))
    with pytest.raises(ValueError, match="全構成音"):
        run(note_range=(61, 66), sections=[])


def test_input_and_nested_pitches_preserved_and_chain():
    song, occurrences = fixture()
    source = [(0, [60, 64, 67], 5, 90)]
    destination = part(octave=1)
    snapshot = copy.deepcopy((song, occurrences, source, destination))
    first = compile_copy(destination, song, occurrences, source)
    second = compile_copy(part(octave=-1), song, occurrences, first)
    assert second == [(0, [60, 64, 67], 4, 90)]
    assert (song, occurrences, source, destination) == snapshot
    first[0][1][0] = 0
    assert source[0][1][0] == 60 and second[0][1][0] == 60


def test_graph_order_chains_and_declaration_order_independence():
    source = {"name": "melody", "role": "melody", "bars": ["C4:4"]}
    a, b = part(name="a"), part(name="b", copy="a")
    for parts in ([b, a, source], [source, b, a], [a, source, b]):
        original = copy.deepcopy(parts)
        assert reference_order(parts) == ["melody", "a", "b"]
        assert parts == original
    # 深い連鎖も再帰制限に依存しない。
    chain = [part(name=str(i), copy=str(i - 1)) for i in range(1, 1500)]
    assert reference_order(list(reversed(chain)) + [{"name": "0", "bars": []}]) == [str(i) for i in range(1500)]


@pytest.mark.parametrize("source", [
    {"role": "melody"}, {"role": "bass", "style": "root_whole"},
    {"role": "chords", "style": "pad"}, {"role": "arrange", "accent": "phrase_start"}, {},
])
def test_pitched_source_roles_allowed(source):
    assert reference_order([part(), {"name": "melody", **source}]) == ["melody", "重ね"]


@pytest.mark.parametrize("source", [
    {"role": "rhythm"}, {"type": "drums"}, {"role": "arrange", "accent": "offbeat_tick"},
    {"role": "unknown"}, {"role": None}, {"type": None}, {"groove": "ambient_none"},
])
def test_drum_and_bad_source_role_type_rejected(source):
    with pytest.raises(ValueError, match="有音程"):
        reference_order([part(sections=[]), {"name": "melody", **source}])


@pytest.mark.parametrize("parts,match", [
    ([part()], "ありません"), ([part(copy="重ね")], "自分自身"),
    ([part(), {"name": "melody", "role": "arrange", "copy": "重ね"}], "循環"),
    ([part(), part()], "重複"), ([{"name": ""}], "name"), ([None], "オブジェクト"),
])
def test_invalid_graph(parts, match):
    with pytest.raises(ValueError, match=match):
        reference_order(parts)


def test_counter_source_order_and_direct_melody_restriction():
    counter = {"name": "response", "role": "arrange", "accent": "counter", "source": "melody"}
    source = {"name": "melody", "role": "melody", "phrases": {}, "grid": "1/8"}
    assert reference_order([counter, source], reference_fields=("copy", "source")) == ["melody", "response"]
    assert reference_order([part(copy="response"), counter, source], reference_fields=("copy", "source")) == [
        "melody", "response", "重ね"]
    for change in ({"role": "arrange"}, {"copy": "other"}, {"accent": "phrase_start"}):
        with pytest.raises(ValueError):
            reference_order([counter, {**source, **change}], reference_fields=("copy", "source"))
    for change in ({"source": None}, {"source": "missing"}, {"accent": "phrase_start"}, {"type": "drums"}, {"bars": []}):
        with pytest.raises(ValueError):
            reference_order([{**counter, **change}, source], reference_fields=("copy", "source"))
    with pytest.raises(ValueError):
        reference_order([{"name": "response", "role": "arrange", "accent": "counter"}])


def test_instrument_inheritance_override_and_independent_fields():
    instruments = {"melody": "kalimba"}
    p = part(volume=-9, mute=False, pan=.5)
    assert resolve_copy_instrument(p, instruments) == "kalimba"
    instruments["重ね"] = resolve_copy_instrument(p, instruments)
    assert resolve_copy_instrument(part(copy="重ね"), instruments) == "kalimba"
    assert resolve_copy_instrument(part(instrument="pad"), {}) == "pad"
    assert p == part(volume=-9, mute=False, pan=.5)
    with pytest.raises(ValueError, match="未解決"):
        resolve_copy_instrument(part(), {})
    for instrument in (None, "", [], 12):
        with pytest.raises(ValueError, match="instrument"):
            resolve_copy_instrument(part(instrument=instrument), instruments)


@pytest.mark.parametrize("field", ["bars", "phrases", "grid", "style", "groove", "accent", "source", "velocity", "kit", "voices"])
@pytest.mark.parametrize("value", [None, [], ""])
def test_conflicts_by_presence(field, value):
    with pytest.raises(ValueError, match="併用"):
        run(**{field: value})


@pytest.mark.parametrize("fields", [
    {"copy": None}, {"copy": []}, {"copy": ""}, {"role": None}, {"type": "drums"},
    {"octave": True}, {"transpose": .5}, {"sections": None}, {"sections": ["missing"]},
    {"instrument": None},
])
def test_bad_fields_even_empty_selection(fields):
    with pytest.raises(ValueError, match=r"\[重ね\] 1番目の小節"):
        run(**{"sections": [], **fields})


@pytest.mark.parametrize("meter", ["5/4", None, [], "6/4"])
def test_unsupported_meter_even_empty(meter):
    with pytest.raises(ValueError, match="meter"):
        run(meter=meter, sections=[])


@pytest.mark.parametrize("note_range", [(70, 60), (0, 128), (False, 90), None, (0,)])
def test_invalid_range_even_empty(note_range):
    with pytest.raises(ValueError, match="note_range"):
        run([], note_range=note_range, sections=[])


@pytest.mark.parametrize("events", [
    None, [None], [(0, [60], 1)], [(float("nan"), [60], 1, 90)],
    [(0, [], 1, 90)], [(0, [True], 1, 90)], [(0, [128], 1, 90)],
    [(0, [60], 0, 90)], [(0, [60], float("inf"), 90)], [(0, [60], 1, 0)],
    [(2, [60], 1, 90), (1, [60], 1, 90)], [(16, [60], 1, 90)],
])
def test_invalid_source_events_even_empty(events):
    song, occurrences = fixture()
    with pytest.raises(ValueError):
        compile_copy(part(sections=[]), song, occurrences, events)


def test_bad_source_event_reports_unfolded_global_bar():
    with pytest.raises(ValueError, match=r"\[重ね\] 4番目の小節"):
        run([(12.5, [60], -1, 90)])


@pytest.mark.parametrize("change", [{"start_beat": -1}, {"bars": True}, {"start_bar": 0}, {"source": ""}, {"name": None}])
def test_invalid_occurrence_even_empty(change):
    song, occurrences = fixture()
    occurrences[0].update(change)
    with pytest.raises(ValueError):
        compile_copy(part(sections=[]), song, occurrences, [])


def test_duplicate_events_order_and_cross_process_determinism():
    events = [(0, [67, 60, 64], 1, 82), (0, [60], .5, 76), (4 / 3, [62, 69], .125, 91)]
    expected = run(events, octave=1, transpose=-2)
    song, occurrences = fixture()
    script = ("import json; from bgm.arrange_copy import compile_copy; "
              f"print(json.dumps(compile_copy({part(octave=1, transpose=-2)!r}, {song!r}, {occurrences!r}, {events!r})))")
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == json.loads(json.dumps(expected))
    assert expected == [(0, [77, 70, 74], 1, 82), (0, [70], .5, 76), (4 / 3, [72, 79], .125, 91)]
