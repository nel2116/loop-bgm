"""固定フィルの通算小節・置換・元identity引渡しを音源なしで検査する。"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bgm.instruments import PERCUSSION, SYNTH_DRUMS
from bgm.rhythm import compile_rhythm
from bgm.structure import expand_form
from bgm.variation_fill import compile_fill

CATALOG = set(PERCUSSION) | set(SYNTH_DRUMS)
TABLE = {
    "4/4": [(0, "kick", 110), (2, "kick", 110), (2, "snare", 75), (2.5, "snare", 85),
            (3, "snare", 95), (3.5, "snare", 105)],
    "3/4": [(0, "kick", 110), (1, "snare", 75), (1.5, "snare", 85), (2, "snare", 95), (2.5, "snare", 105)],
    "6/8": [(0, "kick", 110), (1.5, "kick", 110), (1.5, "snare", 85), (2, "snare", 95), (2.5, "snare", 105)],
}


def song(meter="4/4", bars=8):
    return {"meter": meter, "form": ["A"], "sections": {"A": {"bars": bars}}}


def run(part=None, design=None, events=None, every=8, available=CATALOG):
    design = song() if design is None else design
    part = {"name": "drums", "type": "drums", "bars": []} if part is None else part
    return compile_fill(part, design, expand_form(design), [] if events is None else events,
                        every=every, available_voices=available)


@pytest.mark.parametrize("meter", TABLE)
def test_full_exact_tables_and_global_bar(meter):
    beats = 4 if meter == "4/4" else 3
    start = 7 * beats
    result = run(design=song(meter))
    assert result == {"events": [(start + t, v, vel) for t, v, vel in TABLE[meter]],
                      "origins": [None] * len(TABLE[meter]), "fill_bars": [8]}
    assert all(start <= t < 8 * beats for t, _, _ in result["events"])


@pytest.mark.parametrize("bars,expected", [(1, []), (7, []), (8, [8]), (9, [8]), (15, [8]),
                                           (16, [8, 16]), (17, [8, 16]), (24, [8, 16, 24])])
def test_complete_groups_only(bars, expected):
    assert run(design=song(bars=bars))["fill_bars"] == expected


@pytest.mark.parametrize("every", [1, 2, 3, 8, 10**400])
def test_arbitrary_positive_integer_every(every):
    assert run(design=song(bars=9), every=every)["fill_bars"] == list(range(every, 10, every))


@pytest.mark.parametrize("selection,expected", [(None, [8]), (["A"], []), (["A'"], []), (["B"], [8]), ([], [])])
def test_occurrences_prime_and_selection_gaps_do_not_reset(selection, expected):
    design = {"meter": "4/4", "form": ["A", "A'", "B", "A"],
              "sections": {"A": {"bars": 3}, "B": {"bars": 2}}}
    part = {"name": "drums", "type": "drums"}
    if selection is not None:
        part["sections"] = selection
    assert run(part, design)["fill_bars"] == expected


def test_gap_and_all_repeated_exact_occurrences():
    design = {"meter": "4/4", "form": ["A", "A'", "A"], "sections": {"A": {"bars": 8}}}
    assert run({"type": "drums", "sections": ["A"]}, design)["fill_bars"] == [8, 24]
    assert run({"type": "drums", "sections": ["A'"]}, design)["fill_bars"] == [16]


def test_replace_all_voices_half_open_boundaries_and_original_indices():
    events = [(32, "hat", 76), (27.999, "noise_hit", 80), (28, "kick", 95), (31.999, "ride", 70),
              (0, "noise_hit", 80), (0, "noise_hit", 80), (32, "hat", 76)]
    before = copy.deepcopy(events)
    result = run(design=song(bars=9), events=events)
    assert result["events"] == [events[4], events[5], events[1]] + [
        (28 + t, voice, vel) for t, voice, vel in TABLE["4/4"]] + [events[0], events[6]]
    assert result["origins"] == [4, 5, 1] + [None] * 6 + [0, 6]
    assert events == before


@pytest.mark.parametrize("sections", [None, []])
def test_noop_retains_nonchronological_source_order(sections):
    events = [(20, "hat", 70), (0, "kick", 90), (1, "snare", 80)]
    part = {"type": "drums"}
    if sections is not None:
        part["sections"] = sections
    result = run(part, song(bars=7), events)
    assert result == {"events": events, "origins": [0, 1, 2], "fill_bars": []}
    result["events"].clear()
    assert len(events) == 3


@pytest.mark.parametrize("groove,meter", [("8beat", "4/4"), ("march", "4/4"), ("march", "6/8"),
                                        ("waltz", "3/4"), ("16beat", "4/4"), ("bossa", "4/4"),
                                        ("ambient_none", "4/4"), ("ambient_none", "3/4"), ("ambient_none", "6/8")])
def test_existing_grooves_and_empty_bars_share_fill(groove, meter):
    design = song(meter)
    part = {"name": "drums", "role": "rhythm", "groove": groove}
    source = compile_rhythm(part, design, expand_form(design), available_voices=CATALOG)
    result = run(part, design, source)
    start = 7 * (4 if meter == "4/4" else 3)
    assert [e for e in result["events"] if e[0] >= start] == [(start + t, v, vel) for t, v, vel in TABLE[meter]]
    assert [(e, i) for e, i in zip(result["events"], result["origins"], strict=True) if i is not None] == [
        (e, i) for i, e in enumerate(source) if e[0] < start]


@pytest.mark.parametrize("groove", ["shuffle", "swing_ride"])
def test_fixed_two_to_one_and_no_double_swing(groove):
    part = {"role": "rhythm", "groove": groove}
    assert run(part)["events"] == [(28, "kick", 110), (30, "kick", 110), (30, "snare", 75),
                                    (28 + 2 + 2/3, "snare", 85), (31, "snare", 95), (28 + 3 + 2/3, "snare", 105)]
    for swing in [.6, -1, 1e300]:
        with pytest.raises(ValueError, match="song.swing"):
            run(part | {"sections": []}, song() | {"swing": swing})


@pytest.mark.parametrize("meter", TABLE)
@pytest.mark.parametrize("fields", [{"role": "rhythm", "groove": "bongo_8beat"},
                                   {"type": "drums", "kit": ["bongo_hi", "bongo_lo"]}])
def test_real_bongo_family(meter, fields):
    if "groove" in fields and meter != "4/4":
        with pytest.raises(ValueError, match="対応していません"):
            run(fields, song(meter))
        return
    result = run(fields, song(meter))
    start = 7 * (4 if meter == "4/4" else 3)
    assert result["events"] == [(start + t, "bongo_lo" if v == "kick" else "bongo_hi", vel) for t, v, vel in TABLE[meter]]


def test_mixed_kit_and_available_catalog_do_not_infer_bongo():
    for kit in [None, ["bongo_hi", "bongo_lo", "kick", "snare"]]:
        part = {"type": "drums"}
        if kit is not None:
            part["kit"] = kit
        assert run(part)["events"] == run()["events"]
    with pytest.raises(ValueError, match="必要な打楽器"):
        run({"type": "drums", "kit": ["bongo_hi", "bongo_lo", "kick"]})


@pytest.mark.parametrize("velocity,expected", [(1, [16, 16, 1, 1, 1, 11]), (2, [17, 17, 1, 1, 2, 12]),
                                             (94.5, [110, 110, 74, 84, 94, 104]),
                                             (95, [110, 110, 75, 85, 95, 105]), (127, [127, 127, 107, 117, 127, 127])])
def test_velocity_round_once_then_clamp(velocity, expected):
    assert [e[2] for e in run({"type": "drums", "velocity": velocity})["events"]] == expected


@pytest.mark.parametrize("every", [None, True, False, 0, -1, 8.0, "8", [], float("nan"), float("inf")])
def test_invalid_every(every):
    with pytest.raises(ValueError, match=r"\[drums\] 1番目の小節: .*every"):
        run(every=every)


@pytest.mark.parametrize("field,value", [
    ("velocity", v) for v in [True, None, "95", 0, 128, float("inf"), float("nan"), 10**400]
] + [("sections", v) for v in [None, "A", ["unknown"], [True], [[]]]]
    + [("kit", v) for v in [None, {}, "kick", [], ["kick"], ["bongo"], ["hihat"], [[]]]]
    + [("voices", v) for v in [None, [], {"unknown": None}, {"hat": 2}, {"hat": {"pan": float("nan")}},
                               {"hat": {"volume": 10**400}}]]
    + [(field, None) for field in ["instrument", "phrases", "grid", "style", "accent", "copy", "source"]])
def test_invalid_settings_even_noop(field, value):
    for selection in [None, []]:
        part = {"name": "drums", "type": "drums"}
        if selection is not None:
            part["sections"] = selection
        part[field] = value
        with pytest.raises(ValueError, match=r"\[drums\] [0-9]+番目の小節:"):
            run(part, song(bars=1))


@pytest.mark.parametrize("part", [{}, {"type": "notes"}, {"type": "drums", "role": "arrange"},
                                  {"type": "drums", "groove": "8beat", "bars": []},
                                  {"type": "drums", "groove": None}, {"type": "drums", "bars": None},
                                  {"type": "drums", "bars": [None]}, {"type": "drums", "bars": [{"kick": None}]},
                                  {"type": "drums", "bars": [{"kick": "?"}]},
                                  {"type": "drums", "bars": [{"missing": "."}]}])
def test_invalid_notation(part):
    with pytest.raises(ValueError):
        run(part)


@pytest.mark.parametrize("meter", [None, [], "5/4", "6/4", True])
def test_invalid_meter(meter):
    with pytest.raises(ValueError, match="meter"):
        compile_fill({"type": "drums"}, {"meter": meter}, [], [], every=8)


@pytest.mark.parametrize("field,value", [("name", None), ("source", ""), ("occurrence", 1), ("occurrence", False),
                                        ("start_bar", 2), ("bars", True), ("bars", 0), ("bars", 10**400),
                                        ("start_beat", float("nan")), ("start_beat", 1)])
def test_invalid_occurrences(field, value):
    occurrences = expand_form(song())
    occurrences[0][field] = value
    with pytest.raises(ValueError, match="occurrences"):
        compile_fill({"type": "drums"}, song(), occurrences, [], every=8)


@pytest.mark.parametrize("events", [None, (), [None], [[0, "kick", 95]], [(0, "kick")], [(True, "kick", 95)],
                                    [(float("nan"), "kick", 95)], [(-.1, "kick", 95)], [(32, "kick", 95)],
                                    [(0, [], 95)], [(0, "bongo", 95)], [(0, "kick", True)], [(0, "kick", 0)],
                                    [(0, "kick", float("inf"))], [(0, "kick", 10**400)]])
def test_source_validation_precedes_replacement_and_noop(events):
    for selection in [None, []]:
        part = {"type": "drums"}
        if selection is not None:
            part["sections"] = selection
        with pytest.raises(ValueError, match="source_events"):
            compile_fill(part, song(), expand_form(song()), events, every=1, available_voices=CATALOG)


@pytest.mark.parametrize("catalog", ["kick", None, [None], [[]], {"snare"}, []])
def test_missing_catalog_never_falls_back(catalog):
    if catalog is None:
        assert run(available=catalog)["events"] == run()["events"]
    else:
        with pytest.raises(ValueError, match="available_voices"):
            run(available=catalog)
    with pytest.raises(ValueError):
        run({"role": "rhythm", "groove": "bongo_8beat"}, available=None)


@pytest.mark.parametrize("field,value", [("swing", True), ("swing", None), ("swing", float("inf")),
                                        ("swing_unit", 0), ("swing_unit", False), ("swing_unit", float("nan"))])
def test_invalid_swing_even_noop(field, value):
    with pytest.raises(ValueError, match="song.swing"):
        run({"type": "drums", "sections": []}, song(bars=1) | {field: value})


def test_existing_swing_validation_without_applying_twice():
    assert run(design=song() | {"swing": .6}) == run()
    for swing, unit in [(3, .5), (-16, .5), (1, 5e-324), (10**400, .5)]:
        for part in [{"type": "drums"}, {"type": "drums", "sections": []}]:
            with pytest.raises(ValueError, match="song.swing"):
                run(part, design=song() | {"swing": swing, "swing_unit": unit})


@pytest.mark.parametrize("part,design,occurrences", [(None, {}, []), ([], {}, []), ({}, None, []),
                                                   ({"type": "drums"}, song(), []),
                                                   ({"type": "drums"}, song(), None)])
def test_top_level_invalid_inputs(part, design, occurrences):
    with pytest.raises(ValueError, match=r"番目の小節:"):
        compile_fill(part, design, occurrences, [], every=8)


def test_occurrences_fail_at_global_bar_of_corruption():
    design = {"meter": "4/4", "form": ["A", "A'"], "sections": {"A": {"bars": 8}}}
    occurrences = expand_form(design)
    occurrences[1]["start_beat"] = 0
    with pytest.raises(ValueError, match=r"\[drums\] 9番目の小節: .*occurrences"):
        compile_fill({"name": "drums", "type": "drums"}, design, occurrences, [], every=8)


def test_global_error_location_for_bad_source_and_fill_voice():
    with pytest.raises(ValueError, match=r"\[drums\] 8番目の小節: .*velocity"):
        run(events=[(28, "kick", 128)])
    with pytest.raises(ValueError, match=r"\[drums\] 8番目の小節: .*必要な打楽器"):
        run(available={"kick"})


def test_valid_voices_config_is_preserved_and_inputs_are_immutable():
    part = {"name": "drums", "type": "drums", "bars": [{"hat": "x..o"}],
            "voices": {"hat": None, "snare": {"pan": .2, "volume": .7}}}
    design = song()
    occurrences = expand_form(design)
    source = [(0, "hat", 80), (28, "hat", 80)]
    before = copy.deepcopy((part, design, occurrences, source, CATALOG))
    result = compile_fill(part, design, occurrences, source, every=8, available_voices=CATALOG)
    assert (part, design, occurrences, source, CATALOG) == before
    assert result == compile_fill(part, design, occurrences, source, every=8, available_voices=CATALOG)
    result["origins"].clear()
    result["fill_bars"].append(100)
    assert (part, design, occurrences, source, CATALOG) == before


def test_pure_imports_process_determinism_and_own_checkout():
    root = Path(__file__).resolve().parents[1]
    code = '''
import importlib.abc, json, pathlib, sys
class NoAudio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"bgm.render", "bgm.synth", "bgm.sampler", "bgm.instruments", "bgm.variation", "bgm.variation_period"}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoAudio())
from bgm import variation_fill
from bgm.structure import expand_form
assert pathlib.Path(variation_fill.__file__).resolve().parent.parent == pathlib.Path.cwd()
s = {"meter":"4/4","form":["A"],"sections":{"A":{"bars":8}}}
print(json.dumps(variation_fill.compile_fill({"type":"drums"},s,expand_form(s),[],every=8)))
'''
    outputs = []
    for seed in ["1", "987"]:
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(root))
        proc = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        outputs.append(json.loads(proc.stdout))
    assert outputs[0] == outputs[1] == json.loads(json.dumps(run()))
