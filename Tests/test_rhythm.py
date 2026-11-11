"""固定リズムの打点・強弱・入力検証を音源なしで確認する。"""

import copy
import json
import subprocess
import sys

import pytest

from bgm.rhythm import compile_rhythm
from bgm.structure import expand_form


def song(meter="4/4", *, form=None, bars=1):
    return {"meter": meter, "form": form or ["A"], "sections": {"A": {"bars": bars}, "B": {"bars": 1}}}


def compile(groove="8beat", meter="4/4", **fields):
    design = song(meter)
    return compile_rhythm({"name": "drums", "groove": groove, **fields}, design, expand_form(design))


EIGHT = [
    (0, "kick", 114), (0, "hat", 91), (.5, "hat", 76),
    (1, "snare", 95), (1, "hat", 76), (1.5, "hat", 76),
    (2, "kick", 114), (2, "hat", 91), (2.5, "hat", 76),
    (3, "snare", 95), (3, "hat", 76), (3.5, "hat", 76),
]


@pytest.mark.parametrize(("groove", "meter", "expected"), [
    ("8beat", "4/4", EIGHT),
    ("march", "4/4", [(0, "kick", 114), (1, "snare", 95), (2, "kick", 114), (3, "snare", 95)]),
    ("march", "6/8", [(0, "kick", 114), (1.5, "snare", 114)]),
    ("waltz", "3/4", [(0, "kick", 114), (0, "hat", 91), (1, "snare", 95),
                      (1, "hat", 76), (2, "snare", 95), (2, "hat", 76)]),
    *[("ambient_none", meter, []) for meter in ("4/4", "3/4", "6/8")],
])
def test_exact_events(groove, meter, expected):
    assert compile(groove, meter) == expected
    assert len(compile(groove, meter)) == len(expected)


@pytest.mark.parametrize(("groove", "meter"), [
    ("8beat", "3/4"), ("8beat", "6/8"), ("march", "3/4"), ("waltz", "4/4"), ("waltz", "6/8"),
])
def test_all_unsupported_pairs_positioned_even_unselected(groove, meter):
    design = song(meter, form=["A", "B"])
    for selection, bar in [(["B"], 2), ([], 1)]:
        with pytest.raises(ValueError, match=rf"\[drums\] {bar}番目の小節: .*対応していません"):
            compile_rhythm({"name": "drums", "groove": groove, "sections": selection}, design, expand_form(design))


@pytest.mark.parametrize(("groove", "meter", "count", "last"), [
    ("8beat", "4/4", 12, 3.5), ("march", "4/4", 4, 3),
    ("march", "6/8", 2, 1.5), ("waltz", "3/4", 6, 2),
])
def test_occurrence_boundaries_and_no_fills(groove, meter, count, last):
    design = song(meter, form=["A", "B", "A", "A'"], bars=2)
    occurrences = expand_form(design)
    events = compile_rhythm({"groove": groove}, design, occurrences)
    beats = 4 if meter == "4/4" else 3
    reference = compile(groove, meter)
    assert len(events) == 7 * count
    for bar in range(7):
        assert [e for e in events if bar * beats <= e[0] < (bar + 1) * beats] == [
            (t + bar * beats, voice, velocity) for t, voice, velocity in reference
        ]
    assert events[-1][0] == 6 * beats + last
    for selection, chosen in [(["A"], [0, 1, 3, 4]), (["A'"], [5, 6]), (["B"], [2]), ([], [])]:
        actual = compile_rhythm({"groove": groove, "sections": selection}, design, occurrences)
        assert actual == [(t + bar * beats, v, vel) for bar in chosen for t, v, vel in reference]


def test_velocity_rounds_once_and_clamps():
    assert compile(velocity=2)[1] == (0, "hat", 2)
    assert compile(velocity=127)[0] == (0, "kick", 127)
    assert compile(velocity=1)[2] == (.5, "hat", 1)
    assert compile(velocity=94.5)[0] == (0, "kick", 113)


def test_catalog_data_kit_and_voices_do_not_remap():
    design = song()
    part = {"groove": "8beat", "kit": ["hat", "snare", "kick", "orch_bd"],
            "voices": {"kick": {"volume": -6, "pan": 2}, "orch_bd": None}}
    assert compile_rhythm(part, design, expand_form(design), available_voices={"kick": {}, "snare": {}, "hat": {}, "orch_bd": {}}) == EIGHT
    assert compile(kit=["kick", "snare", "hat"], voices={"hat": None}) == EIGHT
    assert compile("ambient_none", kit=[]) == []
    assert compile_rhythm({"groove": "ambient_none"}, design, expand_form(design), available_voices=[]) == []


@pytest.mark.parametrize("fields", [
    {"groove": "unknown"}, {"groove": []}, {"role": "bass"}, {"type": "notes"},
    *[{field: value} for field in ("bars", "phrases", "grid", "style") for value in (None, [], "")],
    *[{"velocity": value} for value in (True, False, None, "95", 0, 128, float("nan"), float("inf"), -float("inf"))],
    *[{"sections": value} for value in (None, "A", ["missing"], ["A'"], [True], [[]])],
    *[{"kit": value} for value in (None, {}, "kick", ["bongo"], ["hihat"], ["orch_bd"], [True], [[]], [])],
    *[{"voices": value} for value in (None, [], {"bad": None}, {"hat": 1}, {"hat": []}, {False: {}})],
    *[{"voices": {"hat": {field: value}}} for field in ("pan", "volume")
      for value in (True, "0", None, float("nan"), float("inf"), 1e39)],
])
def test_invalid_part_fields(fields):
    with pytest.raises(ValueError, match=r"\[drums\] 1番目の小節"):
        compile(**fields)


@pytest.mark.parametrize("meter", [None, True, 4, [], "7/8", "3/8", "4/0"])
def test_invalid_meter(meter):
    with pytest.raises(ValueError, match=r"\[drums\] 1番目の小節"):
        compile_rhythm({"name": "drums", "groove": "ambient_none"}, {"meter": meter}, [{}])


@pytest.mark.parametrize("fields", [{"kit": ["bad"]}, {"voices": {"bad": None}}, {"velocity": False}, {"grid": None}])
def test_ambient_still_validates_explicit_inputs(fields):
    with pytest.raises(ValueError, match="番目の小節"):
        compile("ambient_none", **fields)


@pytest.mark.parametrize("catalog", ["kick", True, [True], [[]], [""], 1])
def test_invalid_catalog(catalog):
    design = song()
    with pytest.raises(ValueError, match="available_voices"):
        compile_rhythm({"groove": "ambient_none"}, design, expand_form(design), available_voices=catalog)


def test_missing_catalog_voice_is_not_synth_fallback():
    design = song()
    with pytest.raises(ValueError, match="available_voices"):
        compile_rhythm({"groove": "8beat"}, design, expand_form(design), available_voices={"kick", "snare"})


@pytest.mark.parametrize(("field", "value"), [
    ("start_beat", True), ("start_beat", float("nan")), ("start_beat", float("inf")), ("start_beat", 5),
    ("start_bar", True), ("start_bar", 1), ("bars", 0), ("bars", True), ("name", []), ("source", None),
])
def test_malformed_occurrence_reports_global_bar(field, value):
    design = song(form=["A", "B"])
    occurrences = expand_form(design)
    occurrences[1][field] = value
    with pytest.raises(ValueError, match=r"\[drums\] 2番目の小節"):
        compile_rhythm({"name": "drums", "groove": "8beat"}, design, occurrences)


@pytest.mark.parametrize(("part", "design", "occurrences"), [(None, {}, []), ({}, None, []),
                         ({"groove": "8beat"}, {"meter": "4/4"}, []),
                         ({"groove": "8beat"}, {"meter": "4/4"}, [None])])
def test_malformed_top_level(part, design, occurrences):
    with pytest.raises(ValueError, match="番目の小節"):
        compile_rhythm(part, design, occurrences)


def test_pure_deterministic_without_audio_imports():
    design = song(form=["A", "B", "A", "A'"], bars=2)
    part = {"groove": "8beat", "sections": ["A", "A'"], "voices": {"hat": {"pan": .3}}}
    occurrences = expand_form(design)
    catalog = {"kick", "snare", "hat"}
    before = copy.deepcopy((part, design, occurrences, catalog))
    expected = compile_rhythm(part, design, occurrences, available_voices=catalog)
    compile("march", "6/8")
    assert compile_rhythm(part, design, occurrences, available_voices=catalog) == expected
    assert (part, design, occurrences, catalog) == before
    code = '''
import json, sys
from bgm.rhythm import compile_rhythm
from bgm.structure import expand_form
song = {"meter":"4/4", "form":["A"], "sections":{"A":{"bars":1}}}
print(json.dumps(compile_rhythm({"groove":"8beat"}, song, expand_form(song))))
assert not any("bgm." + m in sys.modules for m in ("sampler", "synth", "render", "fetch", "instruments"))
'''
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
        assert json.loads(result.stdout) == [list(e) for e in EIGHT]


NEW_EXPECTED = {
    "16beat": [(0, "kick", 114), (0, "hat", 91), (.25, "hat", 76), (.5, "hat", 76), (.75, "hat", 76),
               (1, "snare", 95), (1, "hat", 76), (1.25, "hat", 76), (1.5, "hat", 76), (1.75, "hat", 76),
               (2, "kick", 114), (2, "hat", 91), (2.25, "hat", 76), (2.5, "hat", 76), (2.75, "hat", 76),
               (3, "snare", 95), (3, "hat", 76), (3.25, "hat", 76), (3.5, "hat", 76), (3.75, "hat", 76)],
    "shuffle": [(0, "kick", 114), (0, "hat", 91), (2/3, "hat", 76), (1, "snare", 95), (1, "hat", 76),
                (1+2/3, "hat", 76), (2, "kick", 114), (2, "hat", 91), (2+2/3, "hat", 76),
                (3, "snare", 95), (3, "hat", 76), (3+2/3, "hat", 76)],
    "bossa": [(0, "kick", 114), (0, "rim", 114), (0, "hat", 91), (.5, "hat", 76), (1, "hat", 76),
              (1.5, "kick", 95), (1.5, "rim", 95), (1.5, "hat", 76), (2, "kick", 114), (2, "hat", 91),
              (2.5, "hat", 76), (3, "rim", 95), (3, "hat", 76), (3.5, "kick", 95), (3.5, "hat", 76)],
    "swing_ride": [(0, "kick", 114), (0, "ride", 91), (1, "snare", 95), (1, "ride", 76), (1+2/3, "ride", 76),
                   (2, "kick", 114), (2, "ride", 91), (3, "snare", 95), (3, "ride", 76), (3+2/3, "ride", 76)],
    "bongo_8beat": [(0, "bongo_hi", 114), (0, "tambourine", 91), (.5, "bongo_hi", 95), (.5, "tambourine", 76),
                    (1, "bongo_lo", 95), (1, "tambourine", 76), (1.5, "bongo_hi", 95), (1.5, "tambourine", 76),
                    (2, "bongo_hi", 114), (2, "tambourine", 91), (2.5, "bongo_hi", 95), (2.5, "tambourine", 76),
                    (3, "bongo_lo", 95), (3, "tambourine", 76), (3.5, "bongo_hi", 95), (3.5, "tambourine", 76)],
}


def new_compile(groove, design=None, **fields):
    from bgm.instruments import PERCUSSION, SYNTH_DRUMS
    design = design or song()
    return compile_rhythm({"name": "drums", "groove": groove, **fields}, design, expand_form(design),
                          available_voices=PERCUSSION | SYNTH_DRUMS)


@pytest.mark.parametrize("groove", NEW_EXPECTED)
def test_new_full_numeric_schedule_and_sections(groove):
    reference = NEW_EXPECTED[groove]
    assert new_compile(groove) == reference
    design = song(form=["A", "B", "A", "A'"], bars=2)
    design["sections"]["A"]["chords"] = "I ii V | vi"
    before = copy.deepcopy(design)
    for selection, bars in [(None, range(7)), (["A"], [0, 1, 3, 4]), (["A'"], [5, 6]), (["B"], [2]), ([], [])]:
        fields = {} if selection is None else {"sections": selection}
        events = new_compile(groove, design, **fields)
        assert events == [(bar * 4 + t, v, vel) for bar in bars for t, v, vel in reference]
        assert len(events) == len(bars) * len(reference)
        assert all(0 <= t < 28 for t, _, _ in events)
    assert design == before


@pytest.mark.parametrize("groove", NEW_EXPECTED)
@pytest.mark.parametrize("meter", ["3/4", "6/8"])
def test_new_unsupported_meters(groove, meter):
    for selection, bar in [(["B"], 2), ([], 1)]:
        with pytest.raises(ValueError, match=rf"\[drums\] {bar}番目の小節: .*対応していません"):
            new_compile(groove, song(meter, form=["A", "B"]), sections=selection)


@pytest.mark.parametrize("groove", NEW_EXPECTED)
def test_new_voices_catalog_kit_missing_and_unknown(groove):
    from bgm.instruments import PERCUSSION, SYNTH_DRUMS
    available = PERCUSSION | SYNTH_DRUMS
    needed = list(dict.fromkeys(v for _, v, _ in NEW_EXPECTED[groove]))
    assert new_compile(groove, kit=needed, voices={v: None for v in needed}) == NEW_EXPECTED[groove]
    design = song(form=["A", "B"])
    for selected, bar in [(["B"], 2), ([], 1)]:
        part = {"name": "drums", "groove": groove, "sections": selected}
        for voice in needed:
            for fields, catalog in [({}, {k: v for k, v in available.items() if k != voice}),
                                    ({"kit": [v for v in needed if v != voice]}, available)]:
                with pytest.raises(ValueError, match=rf"\[drums\] {bar}番目の小節"):
                    compile_rhythm(part | fields, design, expand_form(design), available_voices=catalog)
        for fields in [{"kit": needed + ["bongo"]}, {"voices": {"bongo": None}}]:
            with pytest.raises(ValueError, match=rf"\[drums\] {bar}番目の小節"):
                new_compile(groove, design, sections=selected, **fields)
    if groove in ("swing_ride", "bongo_8beat"):
        with pytest.raises(ValueError, match="available_voices"):
            compile(groove)


@pytest.mark.parametrize("groove", NEW_EXPECTED)
@pytest.mark.parametrize("velocity", [1, 2, 94.5, 127])
def test_new_velocity_round_once(groove, velocity):
    events = new_compile(groove, velocity=velocity)
    expected = []
    for t, voice, _ in NEW_EXPECTED[groove]:
        factor = .8 if voice in ("hat", "ride", "tambourine") else 1
        expected.append((t, voice, max(1, min(127, round(velocity * factor * (1.2 if t in (0, 2) else 1))))))
    assert events == expected


@pytest.mark.parametrize("groove", NEW_EXPECTED)
@pytest.mark.parametrize(("field", "value"), [
    ("swing", True), ("swing", None), ("swing", "0"), ("swing", float("inf")), ("swing", float("nan")),
    ("swing_unit", False), ("swing_unit", None), ("swing_unit", "0.5"), ("swing_unit", 0),
    ("swing_unit", -.5), ("swing_unit", float("inf")), ("swing_unit", float("nan")),
])
def test_new_invalid_swing_even_empty_selection(groove, field, value):
    design = song(form=["A", "B"])
    design[field] = value
    for sections, bar in [(["B"], 2), ([], 1)]:
        with pytest.raises(ValueError, match=rf"\[drums\] {bar}番目の小節: .*song.swing"):
            new_compile(groove, design, sections=sections)


@pytest.mark.parametrize("groove", ["shuffle", "swing_ride"])
def test_fixed_shuffle_rejects_double_swing(groove):
    for swing in [.6, 1, -1, 1e308]:
        with pytest.raises(ValueError, match="二重適用防止"):
            new_compile(groove, song() | {"swing": swing, "swing_unit": .25})
    for zero in [0, 0.0, -0.0]:
        assert new_compile(groove, song() | {"swing": zero, "swing_unit": 2}) == NEW_EXPECTED[groove]


@pytest.mark.parametrize("groove", ["16beat", "bossa", "bongo_8beat"])
def test_swing_boundaries_and_absolute_phase(groove):
    # 16分の最終打点はunit=.25、8分の最終打点はunit=.5で小節末へ移動する。
    unit = .25 if groove == "16beat" else .5
    for swing in [3, 3.00001, -3.00001, 1e308, 10**400]:
        with pytest.raises(ValueError, match="小節外または非有限"):
            new_compile(groove, song() | {"swing": swing, "swing_unit": unit}, sections=[])
    for swing in [2.999999, -3, .6]:
        assert new_compile(groove, song() | {"swing": swing, "swing_unit": unit}) == NEW_EXPECTED[groove]
    with pytest.raises(ValueError, match="小節外または非有限"):
        new_compile(groove, song() | {"swing": 1, "swing_unit": 5e-324})
    # unitが小節を割り切らない場合、絶対拍で2小節目の打点だけが越境する。
    with pytest.raises(ValueError, match=r"\[drums\] 2番目の小節"):
        new_compile(groove, song(bars=2) | {"swing": -4, "swing_unit": 4})


@pytest.mark.parametrize("groove", NEW_EXPECTED)
def test_new_purity_and_independent_process_determinism(groove):
    catalog = {v: {} for _, v, _ in NEW_EXPECTED[groove]}
    design = song(form=["A", "B", "A", "A'"], bars=2)
    part = {"groove": groove, "sections": ["A", "A'"], "kit": list(catalog), "voices": {v: None for v in catalog}}
    occurrences = expand_form(design)
    before = copy.deepcopy((part, design, occurrences, catalog))
    expected = compile_rhythm(part, design, occurrences, available_voices=catalog)
    compile("march", "6/8")
    assert compile_rhythm(part, design, occurrences, available_voices=catalog) == expected
    assert (part, design, occurrences, catalog) == before
    code = '''
import json, sys
from bgm.rhythm import compile_rhythm
part, song, occurrences, catalog = json.loads(sys.stdin.read())
print(json.dumps(compile_rhythm(part, song, occurrences, available_voices=catalog)))
assert not any("bgm." + m in sys.modules for m in ("sampler", "synth", "render", "fetch", "instruments"))
'''
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", code], input=json.dumps(before), check=True, capture_output=True, text=True)
        assert json.loads(result.stdout) == [list(e) for e in expected]
