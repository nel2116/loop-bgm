"""変化統合用のraw全構成音resolverと、既存None経路を検査する。"""

import copy

import pytest

from bgm.arrange_accents import compile_phrase_start
from bgm.arrange_copy import compile_copy
from bgm.arrange_response import compile_counter
from bgm.bass import compile_bass
from bgm.chords import compile_chords
from bgm.harmony import compile_progression
from bgm.melody import compile_melody
from bgm.render import parse_note_bars
from bgm.structure import expand_form


def design(meter="4/4"):
    return {"key": "C major", "meter": meter, "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": 1, "chords": "Iadd9/3 iii V"}, "B": {"bars": 1, "chords": "iv"}},
            "parts": [{"name": "melody", "role": "melody", "instrument": "square", "bars": ["C4:1 r:3"]}]}


@pytest.mark.parametrize("style", ["pad", "block", "offbeat", "arpeggio_up", "broken", "strum", "waltz"])
@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_chord_raw_full_voicing_and_onset_resolution(style, meter):
    if style == "waltz" and meter != "3/4":
        return
    song = design(meter)
    occ = expand_form(song)
    harmony = compile_progression(song, occ)
    original = copy.deepcopy((song, occ, harmony))
    part = {"name": "arp", "role": "chords", "style": style, "octave": 30, "transpose": 2}
    baseline = compile_chords(part, song, occ, harmony)
    assert compile_chords(part, song, occ, harmony, pitch_resolver=None) == baseline
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, list(raw), bar))
        return [p + 12 for p in raw]

    events = compile_chords(part, song, occ, harmony, note_range=(60, 61), pitch_resolver=resolve)
    assert len(calls) == len(events)
    assert [e[0] for e in events] == [e[0] for e in baseline]
    assert [(e[2], e[3]) for e in events] == [(e[2], e[3]) for e in baseline]
    for event, (beat, raw, bar) in zip(events, calls, strict=True):
        chord = next(c for c in reversed(harmony) if c["beat"] <= beat)
        assert raw == chord["pitches"]
        assert bar == int(beat // (4 if meter == "4/4" else 3)) + 1
        assert all(p in [r + 12 for r in raw] for p in event[1])
    assert (song, occ, harmony) == original


@pytest.mark.parametrize("style", ["root_whole", "root_quarter", "root_fifth", "octave_8th", "walking", "arpeggio"])
def test_bass_resolver_keeps_schedule_lookahead_and_full_arpeggio(style):
    song = design()
    occ = expand_form(song)
    harmony = compile_progression(song, occ)
    part = {"name": "bass", "role": "bass", "style": style, "octave": 1, "transpose": 2, "sections": ["A", "A'"]}
    baseline = compile_bass(part, song, occ, harmony)
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, list(raw), bar))
        return [p + 14 for p in raw]

    events = compile_bass(part, song, occ, harmony, note_range=(0, 1), pitch_resolver=resolve)
    assert events == baseline
    assert len(calls) == len(events)
    if style == "arpeggio":
        assert calls[0][1] == [p - 12 for p in harmony[0]["pitches"]]
    else:
        assert [raw[0] + 14 for _, raw, _ in calls] == [e[1][0] for e in baseline]


def test_copy_resolves_final_source_full_voicing_before_destination_transforms():
    song = design()
    part = {"name": "copy", "role": "arrange", "copy": "melody", "instrument": "square", "octave": 20}
    source = [(0, [60, 64, 74], 2, 90)]
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, raw, bar))
        return [p - 12 for p in raw]

    events = compile_copy(part, song, expand_form(song), source, note_range=(0, 1), pitch_resolver=resolve)
    assert calls == [(0, [60, 64, 74], 1)]
    assert events == [(0, [48, 52, 62], 2, 90)]
    assert source == [(0, [60, 64, 74], 2, 90)]


def test_degree_resolver_at_onset_preserves_ties_and_ignores_old_part_shift():
    song = design()
    part = {"name": "melody", "grid": "1/4", "phrases": {"A": "[1 3] - - -", "B": "1 - - -"},
            "octave": 20, "transpose": 2}
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, raw, bar))
        return [p + 12 for p in raw]

    events = compile_melody(part, song, expand_form(song), pitch_resolver=resolve)
    assert events[0] == (0, [72, 76], 4, 90)
    assert len(calls) == 4
    assert calls[0] == (0, [60, 64], 1)


def test_absolute_resolver_runs_after_expansion_at_original_global_onsets():
    song = {"bars": 3, "beats_per_bar": 4}
    part = {"name": "absolute", "octave": 2, "transpose": 1, "bars": ["C4+E4:2 r:2"]}
    original = copy.deepcopy((part, song))
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, list(raw), bar))
        return [p + bar for p in raw]

    assert parse_note_bars(part, song, pitch_resolver=resolve) == [
        (0, [61, 65], 2, 90), (4, [62, 66], 2, 90), (8, [63, 67], 2, 90)]
    assert calls == [(0, [60, 64], 1), (4, [60, 64], 2), (8, [60, 64], 3)]
    assert parse_note_bars(part, song, pitch_resolver=None) == parse_note_bars(part, song)
    assert (part, song) == original


@pytest.mark.parametrize("accent", ["phrase_start", "counter"])
def test_accents_resolve_each_actual_onset_without_source_dsp(accent):
    song = design()
    occ = expand_form(song)
    harmony = compile_progression(song, occ)
    part = {"name": "decor", "role": "arrange", "instrument": "square", "accent": accent, "octave": 20}
    calls = []

    def resolve(beat, raw, bar):
        calls.append((beat, raw, bar))
        return [p - 12 for p in raw]

    if accent == "counter":
        part["source"] = "melody"
        events = compile_counter(part, song, occ, harmony, [(0, [60], 1, 90)],
                                 note_range=(0, 1), pitch_resolver=resolve)
    else:
        events = compile_phrase_start(part, song, occ, harmony, note_range=(0, 1), pitch_resolver=resolve)
    assert len(events) == len(calls)
    assert all(e[1] == [c[1][0] - 12] for e, c in zip(events, calls, strict=True))
    assert all(c[0] == e[0] for c, e in zip(calls, events, strict=True))
