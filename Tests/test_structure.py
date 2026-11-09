from copy import deepcopy

import pytest

from bgm.structure import expand_form, grid_to_beats, meter_to_beats


@pytest.mark.parametrize(("meter", "beats"), [("4/4", 4), ("3/4", 3), ("6/8", 3), ("5/8", 2.5)])
def test_meter(meter, beats):
    assert meter_to_beats(meter) == beats


@pytest.mark.parametrize(("grid", "beats"), [("1/4", 1), ("1/8", 0.5), ("1/16", 0.25)])
def test_grid(grid, beats):
    assert grid_to_beats(grid) == beats


@pytest.mark.parametrize("value", [None, True, 4, "", "4", "0/4", "-3/4", "3/0", "3/3", "3/4/4", "3.0/4"])
def test_invalid_meter(value):
    with pytest.raises(ValueError, match="meter"):
        meter_to_beats(value)


@pytest.mark.parametrize("value", [None, 8, "2/8", "1/0", "1/3", "0/8"])
def test_invalid_grid(value):
    with pytest.raises(ValueError, match="grid"):
        grid_to_beats(value)


def song():
    return {"meter": "6/8", "form": ["A", "B", "A"], "sections": {"A": {"bars": 2}, "B": {"bars": 1}}}


def test_order_offsets_and_independent_results():
    design = song()
    original = deepcopy(design)
    expected = [
        {"name": "A", "source": "A", "occurrence": 0, "start_beat": 0, "start_bar": 1, "bars": 2},
        {"name": "B", "source": "B", "occurrence": 1, "start_beat": 6, "start_bar": 3, "bars": 1},
        {"name": "A", "source": "A", "occurrence": 2, "start_beat": 9, "start_bar": 4, "bars": 2},
    ]
    assert expand_form(design) == expand_form(design) == expected
    result = expand_form(design)
    result[0]["bars"] = 99
    assert expand_form(design) == expected
    assert design == original


@pytest.mark.parametrize("defined", [False, True])
def test_prime_uses_source_and_preserves_occurrence(defined):
    design = song()
    design["form"] = ["A", "A'", "A''"]
    if defined:
        design["sections"]["A'"] = deepcopy(design["sections"]["A"])
    original = deepcopy(design)
    occurrences = expand_form(design)
    assert [item["name"] for item in occurrences] == design["form"]
    assert [item["source"] for item in occurrences] == ["A"] * 3
    assert [item["occurrence"] for item in occurrences] == [0, 1, 2]
    assert [item["start_beat"] for item in occurrences] == [0, 6, 12]
    assert [item["start_bar"] for item in occurrences] == [1, 3, 5]
    assert design == original


@pytest.mark.parametrize("bars", [0, -1, 1.5, "2", True, None])
def test_invalid_bars(bars):
    design = song()
    design["sections"]["A"]["bars"] = bars
    with pytest.raises(ValueError, match="bars"):
        expand_form(design)


@pytest.mark.parametrize("form", [[], None, "A", ["C"], ["C'"], [""], ["'"], [None], [" A"]])
def test_invalid_form(form):
    design = song()
    design["form"] = form
    with pytest.raises(ValueError):
        expand_form(design)


@pytest.mark.parametrize("sections", [None, [], {}, {"A": None}, {"A": {}}, {"A'": {"bars": 1}}])
def test_invalid_sections(sections):
    design = song()
    design["sections"] = sections
    with pytest.raises(ValueError):
        expand_form(design)


@pytest.mark.parametrize("prime", [{"bars": 3}, {"bars": 2, "chords": "V | I"}])
def test_conflicting_prime_rejected_without_mutation(prime):
    design = song()
    design["sections"]["A'"] = prime
    original = deepcopy(design)
    with pytest.raises(ValueError, match="競合"):
        expand_form(design)
    assert design == original


def test_invalid_song_and_missing_meter():
    for design in [None, [], {}, {"form": ["A"], "sections": {"A": {"bars": 1}}}]:
        with pytest.raises(ValueError):
            expand_form(design)
