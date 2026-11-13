"""変化計画の構文・区間・音高・休止を音源なしで検証する。"""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from bgm.structure import expand_form
from bgm.variation import (
    InstrumentSpan,
    Interval,
    apply_rest,
    compile_variation,
    resolve_instrument_spans,
    transform_pitches,
)

CATALOG = {"square": (0, 127), "flute": (60, 96), "kalimba": (0, 127), "e_piano": (0, 127)}
VOICES = frozenset(("kick", "snare", "hat", "bongo_lo", "bongo_hi", "tambourine", "ride"))


def design(meter="4/4", bars=2):
    return {"meter": meter, "key": "C major", "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": bars}, "B": {"bars": bars}},
            "parts": [{"name": "melody", "role": "melody", "instrument": "square"},
                      {"name": "drums", "type": "drums", "bars": [{}]},
                      {"name": "arp", "role": "chords", "style": "arpeggio_up", "instrument": "square"}]}


def rule(action="octave_up", **kwargs):
    return dict({"part": "melody", "section": "A'", "do": action}, **kwargs)


def compile(song, **kwargs):
    return compile_variation(song, expand_form(song), pitched_catalog=CATALOG, available_voices=VOICES, **kwargs)


@pytest.mark.parametrize("meter,bpb", [("4/4", 4), ("3/4", 3), ("6/8", 3)])
def test_exact_repeated_occurrences_and_frozen_plan(meter, bpb):
    song = design(meter)
    song["variation"] = [rule(section="A"), rule("instrument", instrument="flute")]
    before = deepcopy(song)
    plan = compile(song)
    assert song == before
    octave = next(r for r in plan.rules if r.action == "octave_up")
    assert octave.intervals == (Interval(0, 2*bpb, 1, 0, "A"), Interval(4*bpb, 6*bpb, 5, 2, "A"))
    instrument = next(r for r in plan.rules if r.action == "instrument")
    assert instrument.intervals == (Interval(6*bpb, 8*bpb, 7, 3, "A'"),)
    assert instrument.instrument == "flute" and instrument.beats is None and instrument.every is None
    with pytest.raises(FrozenInstanceError):
        instrument.instrument = "square"
    song["variation"].reverse()
    assert compile(song) == plan


@pytest.mark.parametrize("variation", [None, {}, "", 0, True, [None], [[]]])
def test_invalid_top_level_and_elements(variation):
    song = design()
    song["variation"] = variation
    with pytest.raises(ValueError, match=r"\[variation\] 1番目の小節"):
        compile(song)


@pytest.mark.parametrize("bad", [
    {}, {"part": "melody"}, {"part": "melody", "do": "octave_up"}, rule(do=None), rule(do=[]), rule(do="unknown"),
    rule(part=None), rule(part=[]), rule(part="missing"), rule(section=None), rule(section=[]), rule(section="Z"),
    rule(every=None), rule(instrument=None), rule(beats=None), rule(unknown=None),
    rule("instrument"), rule("instrument", instrument=None), rule("instrument", instrument=[]),
    rule("instrument", instrument="kick"), rule("rest", instrument="flute"),
    {"part": "drums", "do": "fill_last_bar", "every": 8, "section": None},
    {"part": "drums", "do": "fill_last_bar"},
    {"part": "arp", "do": "period", "beats": 3, "every": None},
])
def test_schema_presence_and_wrong_types(bad):
    song = design()
    song["variation"] = [bad]
    with pytest.raises(ValueError, match="番目の小節"):
        compile(song)


@pytest.mark.parametrize("every", [None, False, 0, -1, 2.5, float("inf"), "8"])
def test_invalid_every_even_when_no_selected_bars(every):
    song = design()
    song["parts"][1]["sections"] = []
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": every}]
    with pytest.raises(ValueError, match="every"):
        compile(song)


@pytest.mark.parametrize("beats", [None, False, 0, -1, "3", [], float("nan"), float("inf"), 5e-324, 10**400])
def test_invalid_period_and_unrepresentable_calculation(beats):
    song = design()
    song["variation"] = [{"part": "arp", "do": "period", "beats": beats}]
    with pytest.raises(ValueError, match="beats"):
        compile(song)


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_period_optional_section_and_non_grid_duration(meter):
    song = design(meter)
    song["variation"] = [{"part": "arp", "do": "period", "beats": 3.1}]
    assert len(compile(song).rules[0].intervals) == 4
    song["variation"][0]["section"] = "A'"
    plan = compile(song)
    assert plan.rules[0].beats == 3.1 and len(plan.rules[0].intervals) == 1


@pytest.mark.parametrize("action", ["octave_up", "instrument", "rest", "period"])
def test_valid_empty_selection_noop_but_validate_settings(action):
    song = design()
    name = "arp" if action == "period" else "melody"
    selected = next(p for p in song["parts"] if p["name"] == name)
    selected["sections"] = []
    item = rule(action, part=name)
    if action == "instrument":
        item["instrument"] = "flute"
    if action == "period":
        item["beats"] = 3
    song["variation"] = [item]
    assert compile(song).rules[0].intervals == ()
    item["unknown"] = None
    with pytest.raises(ValueError):
        compile(song)


def test_selection_intersection_all_rest_and_absence():
    song = design()
    assert compile(song).rules == ()
    song["variation"] = []
    assert compile(song).rules == ()
    song["parts"][0]["sections"] = ["A"]
    song["parts"][0]["bars"] = ["r:4"]
    song["variation"] = [rule()]
    assert compile(song).rules[0].intervals == ()
    song["variation"][0]["section"] = "A"
    assert len(compile(song).rules[0].intervals) == 2


@pytest.mark.parametrize("selected", [None, "A", [None], ["Z"], ["A", "A"]])
def test_bad_part_selection(selected):
    song = design()
    song["parts"][0]["sections"] = selected
    with pytest.raises(ValueError, match="sections"):
        compile(song)


@pytest.mark.parametrize("action", ["octave_up", "instrument", "period", "fill_last_bar"])
def test_target_types(action):
    song = design()
    item = rule(action, part="drums" if action != "fill_last_bar" else "melody")
    if action == "instrument":
        item["instrument"] = "flute"
    if action == "period":
        item["beats"] = 3
    if action == "fill_last_bar":
        item.pop("section")
        item["every"] = 8
    song["variation"] = [item]
    with pytest.raises(ValueError):
        compile(song)


def test_period_rejects_other_styles_and_fill_rejects_tick():
    song = design()
    song["parts"][2]["style"] = "broken"
    song["variation"] = [{"part": "arp", "do": "period", "beats": 3}]
    with pytest.raises(ValueError, match="arpeggio_up"):
        compile(song)
    song["parts"][1] = {"name": "drums", "role": "arrange", "accent": "offbeat_tick"}
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 8}]
    with pytest.raises(ValueError, match="専用"):
        compile(song)


@pytest.mark.parametrize("meter,bpb", [("4/4", 4), ("3/4", 3), ("6/8", 3)])
def test_fill_global_bar_selection_partial_end_and_noop(meter, bpb):
    song = design(meter, bars=5)
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 8}]
    result = compile(song).rules[0]
    assert [(i.start_bar, i.start, i.end) for i in result.intervals] == [(8, 7*bpb, 8*bpb), (16, 15*bpb, 16*bpb)]
    song["parts"][1]["sections"] = ["A"]
    assert compile(song).rules[0].intervals == ()
    song["parts"][1].pop("sections")
    song["variation"][0]["every"] = 21
    assert compile(song).rules[0].intervals == ()


@pytest.mark.parametrize("kit", [["kick"], None, ["unknown"], ["bongo_hi"]])
def test_fill_kit_rejected_even_noop(kit):
    song = design()
    song["parts"][1]["kit"] = kit
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 100}]
    with pytest.raises(ValueError, match="kit"):
        compile(song)


def test_bongo_family_real_catalog_and_mixed_kit():
    song = design()
    song["parts"][1]["kit"] = ["bongo_lo", "bongo_hi"]
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 8}]
    compile_variation(song, expand_form(song), pitched_catalog=CATALOG, available_voices={"bongo_lo", "bongo_hi"})
    song["parts"][1]["kit"] += ["kick", "snare"]
    with pytest.raises(ValueError, match="kit"):
        compile_variation(song, expand_form(song), pitched_catalog=CATALOG, available_voices={"bongo_lo", "bongo_hi"})


@pytest.mark.parametrize("groove,meter,swing", [("shuffle", "4/4", .5), ("swing_ride", "4/4", .5), ("8beat", "3/4", 0)])
def test_fill_preserves_existing_groove_limitations(groove, meter, swing):
    song = design(meter)
    song["swing"] = swing
    song["parts"][1] = {"name": "drums", "groove": groove, "sections": []}
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 100}]
    with pytest.raises(ValueError):
        compile(song)


@pytest.mark.parametrize("a,b", [
    (rule(), rule()), (rule(), rule("rest")),
    (rule("instrument", instrument="flute"), rule("instrument", instrument="kalimba")),
    ({"part": "arp", "do": "period", "beats": 3}, rule("rest", part="arp")),
    ({"part": "drums", "do": "fill_last_bar", "every": 8}, rule("rest", part="drums")),
])
def test_actual_overlap_rejected(a, b):
    song = design()
    song["variation"] = [a, b]
    with pytest.raises(ValueError, match="重"):
        compile(song)


@pytest.mark.parametrize("action", ["period", "fill_last_bar"])
def test_at_most_one_period_fill_even_disjoint_or_empty(action):
    song = design()
    item = {"part": "arp", "do": "period", "beats": 3} if action == "period" else {
        "part": "drums", "do": "fill_last_bar", "every": 100}
    song["variation"] = [item, deepcopy(item)]
    if action == "period":
        song["variation"][0]["section"] = "A"
        song["variation"][1]["section"] = "B"
    with pytest.raises(ValueError, match="1件"):
        compile(song)


def test_nonoverlap_rest_and_composition_are_order_independent():
    song = design()
    song["variation"] = [rule(), rule("instrument", instrument="flute"), rule("rest", section="B"),
                         {"part": "arp", "do": "period", "beats": 3}, rule(part="arp"),
                         rule("instrument", part="arp", instrument="flute")]
    expected = compile(song)
    song["variation"].reverse()
    assert compile(song) == expected


def test_instrument_timeline_chain_override_and_no_source_dsp():
    song = design()
    source = song["parts"][0]
    source.update(pan=.7, gate=.5, strum=.1, volume=.2)
    song["parts"] += [{"name": "chain", "role": "arrange", "copy": "layer"},
                      {"name": "layer", "role": "arrange", "copy": "melody", "octave": 1},
                      {"name": "explicit", "role": "arrange", "copy": "melody", "instrument": "e_piano"}]
    song["variation"] = [rule("instrument", instrument="flute")]
    plan = compile(song)
    before = deepcopy(song)
    spans = resolve_instrument_spans(song["parts"], expand_form(song), plan, pitched_catalog=CATALOG)
    for name in ("melody", "layer", "chain"):
        assert [s for s in spans if s.part == name] == [InstrumentSpan(name, 0, 24, "square", (0, 127)),
                                                       InstrumentSpan(name, 24, 32, "flute", (60, 96))]
    assert [s for s in spans if s.part == "explicit"] == [InstrumentSpan("explicit", 0, 32, "e_piano", (0, 127))]
    assert song == before
    song["variation"].append(rule("instrument", part="layer", instrument="kalimba"))
    spans = resolve_instrument_spans(song["parts"], expand_form(song), compile(song), pitched_catalog=CATALOG)
    assert next(s for s in spans if s.part == "chain" and s.start == 24).instrument == "kalimba"


@pytest.mark.parametrize("change", ["duplicate", "missing", "self", "cycle", "null_instrument", "unknown_instrument"])
def test_graph_and_base_instrument_validated_even_empty(change):
    song = design()
    song["variation"] = []
    if change == "duplicate":
        song["parts"].append(deepcopy(song["parts"][0]))
    elif change in ("missing", "self", "cycle"):
        song["parts"] += [{"name": "layer", "role": "arrange", "copy": {"missing": "Z", "self": "layer", "cycle": "chain"}[change]}]
        if change == "cycle":
            song["parts"].append({"name": "chain", "role": "arrange", "copy": "layer"})
    else:
        song["parts"][0]["instrument"] = None if change == "null_instrument" else "unknown"
        song["variation"] = [rule("instrument", section="A", instrument="flute")]
    with pytest.raises(ValueError):
        compile(song)


def test_existing_names_are_not_trimmed_or_restricted():
    song = design()
    song["parts"][0]["name"] = " lead one "
    song["variation"] = [rule(part=" lead one ")]
    assert compile(song).rules[0].part == " lead one "


@pytest.mark.parametrize("raw,part,up,bounds,expected", [
    ([60, 64, 67], {"octave": -1, "transpose": 2}, 1, (0, 127), [62, 66, 69]),
    ([60, 64, 67], {"transpose": 2}, 1, (60, 72), [62, 66, 69]),
    ([64, 67, 72, 74], {"transpose": 2}, 1, (60, 84), [66, 69, 74, 76]),
    ([67, 60, 64, 60], {}, 0, (67, 79), [79, 72, 76, 72]),
    ([120, 124, 127], {}, 1, (0, 127), [120, 124, 127]),
    ([60], {"octave": 10**100}, 0, (0, 127), [120]),
])
def test_common_pitch_transform(raw, part, up, bounds, expected):
    before = deepcopy(raw)
    assert transform_pitches(part, raw, octave_up=up, note_range=bounds) == expected
    assert raw == before


@pytest.mark.parametrize("raw,kwargs", [
    ([], {}), ([True], {}), ([60.0], {}), ([60, 84], {"note_range": (60, 72)}),
    ([60], {"octave_up": True}), ([60], {"octave_up": 2}), ([60], {"note_range": (72, 60)}),
])
def test_invalid_pitch_transforms(raw, kwargs):
    with pytest.raises(ValueError, match=r"\[lead\] 7番目の小節"):
        transform_pitches({"name": "lead"}, raw, bar=7, **kwargs)


def test_copy_transforms_only_destination_once():
    source = transform_pitches({"octave": 1, "transpose": 2}, [60])
    assert source == [74]
    assert transform_pitches({"octave": 1, "transpose": 3}, source) == [89]


def test_rest_clips_written_hold_and_preserves_indices_and_aliases():
    events = [(2, [60], 4, 90), (4, [62], 1, 90), (7, [64], 2, 90), (8, [65], 1, 90)]
    before = deepcopy(events)
    result = apply_rest(events, [(4, 8)])
    assert result.events == [(2, [60], 2, 90), (8, [65], 1, 90)]
    assert result.indices == (0, 3) and result.windows == ((2, 4), None)
    result.events[0][1][0] = 99
    assert events == before
    assert apply_rest([(2, [60], 16, 90)], [(12, 16), (4, 8)]).events == [(2, [60], 2, 90)]


def test_rest_exact_boundary_duplicates_and_drums():
    events = [(2, "kick", 90), (4, "snare", 90), (7, "hat", 90), (8, "kick", 90), (8, "kick", 90)]
    result = apply_rest(events, [Interval(4, 8, 2, 0, "A")], drums=True)
    assert result.events == [events[i] for i in (0, 3, 4)]
    assert result.indices == (0, 3, 4) and result.windows == (None, None, None)
    notes = [(0, [60], 4, 90), (0, [60], 4, 90)]
    assert apply_rest(notes, [(4, 8)]).indices == (0, 1)
    assert apply_rest(notes, [(4, 8)]).events == notes


@pytest.mark.parametrize("intervals", [[(4, 4)], [(-1, 4)], [(0, float("inf"))], [(0, 4), (3, 5)], [None]])
def test_invalid_rest_intervals(intervals):
    with pytest.raises(ValueError, match="休止区間"):
        apply_rest([], intervals)


@pytest.mark.parametrize("event,drums", [
    ((0, [60], 0, 90), False), ((0, [60], float("inf"), 90), False), ((0, [128], 1, 90), False),
    ((0, [60], 1, 0), False), ((True, [60], 1, 90), False), ((0, None, 90), True), ((0, "kick", 90), False),
])
def test_invalid_events_are_not_hidden_by_rest(event, drums):
    with pytest.raises(ValueError):
        apply_rest([event], [(0, 8)], drums=drums)


@pytest.mark.parametrize("field,value", [("octave", True), ("transpose", 1.5), ("gate", None), ("strum", float("inf")),
                                         ("type", None), ("role", []), ("instrument", None)])
def test_invalid_part_settings_not_hidden_by_empty_selection(field, value):
    song = design()
    song["parts"][0].update(sections=[], **{field: value})
    song["variation"] = [rule()]
    with pytest.raises(ValueError):
        compile(song)


@pytest.mark.parametrize("field", ["bars", "phrases", "grid", "groove", "accent"])
def test_period_notation_conflicts_by_presence(field):
    song = design()
    song["parts"][2][field] = None
    song["variation"] = [{"part": "arp", "do": "period", "beats": 3}]
    with pytest.raises(ValueError):
        compile(song)


def test_missing_base_instrument_cannot_be_hidden_by_complete_override():
    song = design()
    song["parts"][0].pop("instrument")
    song["variation"] = [rule("instrument", section=s, instrument="flute") for s in ("A", "B", "A'")]
    with pytest.raises(ValueError, match="instrument"):
        compile(song)


@pytest.mark.parametrize("voices", [None, {"unknown": {}}, {"kick": []}, {"kick": {"pan": None}}, {"kick": {"volume": 10**400}}])
def test_fill_voice_settings_validated_before_empty_noop(voices):
    song = design()
    song["parts"][1].update(voices=voices, sections=[])
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": 100}]
    with pytest.raises(ValueError, match="voices"):
        compile(song)


def test_negative_strum_gate_are_preserved_and_plan_does_not_apply_dsp():
    song = design()
    song["parts"][0].update(gate=-1, strum=-.02)
    song["variation"] = [rule()]
    before = deepcopy(song)
    assert compile(song).rules[0].action == "octave_up"
    assert song == before


def test_separate_process_determinism_and_no_audio_imports():
    song = design()
    song["variation"] = [rule(), rule("instrument", instrument="flute"),
                         {"part": "drums", "do": "fill_last_bar", "every": 8}]
    payload = json.dumps(song)
    script = """
import json, sys
from dataclasses import asdict
from bgm.variation import compile_variation
from bgm.structure import expand_form
song = json.loads(sys.argv[1])
plan = compile_variation(song, expand_form(song), pitched_catalog={'square':(0,127),'flute':(60,96)},
                         available_voices={'kick','snare'})
assert not {'bgm.render','bgm.synth','bgm.sampler','soundfile','numpy'} & set(sys.modules)
print(json.dumps(asdict(plan), sort_keys=True))
"""
    results = [subprocess.run([sys.executable, "-c", script, payload], capture_output=True, text=True, check=True).stdout
               for _ in range(2)]
    assert results[0] == results[1]


@pytest.mark.parametrize("catalog", [None, {"square": (128, 129)}, {"square": (True, 127)}, {"": (0, 127)}])
def test_invalid_catalog_data(catalog):
    song = design()
    with pytest.raises(ValueError):
        compile_variation(song, expand_form(song), pitched_catalog=catalog, available_voices=VOICES)


def test_bad_occurrences_report_japanese_error():
    song = design()
    occurrences = expand_form(song)
    occurrences[1]["start_bar"] = 100
    with pytest.raises(ValueError, match=r"\[variation\] 3番目の小節"):
        compile_variation(song, occurrences, pitched_catalog=CATALOG, available_voices=VOICES)


def test_empty_rules_with_distinct_instruments_still_have_canonical_order():
    song = design()
    song["parts"][0]["sections"] = []
    song["variation"] = [rule("instrument", instrument=i) for i in ("square", "flute")]
    plan = compile(song)
    song["variation"].reverse()
    assert compile(song) == plan
