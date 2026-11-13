"""#60 受け入れ条件のうち、統合経路(compile_song・part_hash・CLI)で確かめる項目。"""

import copy
import json
import subprocess
import sys

import pytest
from test_variation_integration import design, load

from bgm import render

FILL = {  # 共有契約B: 拍頭からのオフセット(四分音符拍)。L=kick、H=snare
    "4/4": ([0, 2], [2, 2.5, 3, 3.5]),
    "3/4": ([0], [1, 1.5, 2, 2.5]),
    "6/8": ([0, 1.5], [1.5, 2, 2.5]),
}


def drum_song(meter, every):
    song = design(meter)
    song["parts"][4]["bars"] = [{"kick": "x..."}]
    song["variation"] = [{"part": "drums", "do": "fill_last_bar", "every": every}]
    return song


def fill_bars(compiled):
    beats = compiled["beats_per_bar"]
    plain_first = sorted({e[0] for e in compiled["rhythm"]["drums"] if e[0] < beats})
    bars = {}
    for beat, voice, _velocity in compiled["rhythm"]["drums"]:
        bars.setdefault(int(beat // beats), []).append((round(beat % beats, 6), voice))
    return plain_first, bars


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_fill_table_per_meter_at_global_bar_8(tmp_path, meter):
    compiled = render.compile_song(load(tmp_path, drum_song(meter, 8)))
    _, bars = fill_bars(compiled)
    low, high = FILL[meter]
    expected = sorted([(float(o), "kick") for o in low] + [(float(o), "snare") for o in high])
    assert sorted(bars[7]) == expected
    plain = render.compile_song(load(tmp_path, {k: v for k, v in drum_song(meter, 8).items() if k != "variation"}))
    _, plain_bars = fill_bars(plain)
    assert all(bars[b] == plain_bars[b] for b in range(7))


@pytest.mark.parametrize("every,targets", [(3, {2, 5}), (4, {3, 7}), (5, {4})])
def test_every_counts_global_bars_without_occurrence_reset(tmp_path, every, targets):
    compiled = render.compile_song(load(tmp_path, drum_song("4/4", every)))
    _, bars = fill_bars(compiled)
    filled = {b for b, hits in bars.items() if any(v == "snare" for _, v in hits)}
    assert filled == targets


def test_section_rule_applies_to_every_occurrence_of_a_and_never_a_prime(tmp_path):
    song = design()
    song["variation"] = [{"section": "A", "part": "melody", "do": "octave_up"}]
    compiled = render.compile_song(load(tmp_path, song))
    by_bar = {int(e[0] // 4): e[1] for e in compiled["notes"]["melody"]}
    assert by_bar[0] == [72, 76] and by_bar[4] == [72, 76]  # 1回目と2回目のA
    assert by_bar[2] == [60, 64] and by_bar[6] == [60, 64]  # BとA'


def test_part_sections_intersection_limits_variation(tmp_path):
    song = design()
    song["parts"][2]["sections"] = ["A", "A'"]
    song["variation"] = [{"section": "A'", "part": "melody", "do": "octave_up"}]
    compiled = render.compile_song(load(tmp_path, song))
    by_bar = {int(e[0] // 4): e[1] for e in compiled["notes"]["melody"]}
    assert set(by_bar) == {0, 4, 6}
    assert by_bar[6] == [72, 76] and by_bar[0] == by_bar[4] == [60, 64]


def varied_song():
    song = design()
    song["variation"] = [{"section": "A'", "part": "melody", "do": "octave_up"},
                         {"part": "arp", "do": "period", "beats": 3}]
    return song


def hashes(song):
    return {p["name"]: render.part_hash(p, song) for p in song["parts"]}


def test_unrelated_part_insertion_and_mix_only_changes_keep_hashes(tmp_path):
    song = varied_song()
    reference = hashes(load(tmp_path, song))
    added = copy.deepcopy(song)
    added["parts"].append({"name": "pad", "role": "chords", "style": "block", "instrument": "square"})
    assert {k: v for k, v in hashes(load(tmp_path, added)).items() if k != "pad"} == reference
    mixed = copy.deepcopy(song)
    for part in mixed["parts"]:
        part.update(volume=.3, pan=-.4)
    assert hashes(load(tmp_path, mixed)) == reference


def test_source_change_invalidates_only_dependents(tmp_path):
    song = varied_song()
    reference = hashes(load(tmp_path, song))
    changed = copy.deepcopy(song)
    changed["parts"][2]["bars"] = ["D4+F4:8"]
    after = hashes(load(tmp_path, changed))
    # counterは元の音高ではなく鳴っている区間だけに依存するので、音高変更では変わらない
    assert {n for n in reference if reference[n] != after[n]} == {"melody", "copy"}
    rhythm = copy.deepcopy(song)
    rhythm["parts"][2]["bars"] = ["C4+E4:4 r:4"]
    after = hashes(load(tmp_path, rhythm))
    assert {n for n in reference if reference[n] != after[n]} == {"melody", "copy", "counter"}
    rule = copy.deepcopy(song)
    rule["variation"][1]["beats"] = 5
    after = hashes(load(tmp_path, rule))
    assert {n for n in reference if reference[n] != after[n]} == {"arp"}


@pytest.mark.parametrize("command", ["render", "listen"])
@pytest.mark.parametrize("variation", [[{"section": "A", "part": "nobody", "do": "rest"}],
                                      [{"part": "drums", "do": "fill_last_bar", "every": 0}]])
def test_cli_rejects_invalid_variation_in_japanese_without_traceback(tmp_path, command, variation):
    song = design()
    song["variation"] = variation
    (tmp_path / "song.json").write_text(json.dumps(song), encoding="utf-8")
    args = [sys.executable, "-X", "utf8", "-m", "bgm", command, str(tmp_path)] + (["--no-mp3"] if command == "render" else [])
    result = subprocess.run(args, capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "小節" in result.stderr and "[" in result.stderr
    assert {p.name for p in tmp_path.iterdir()} == {"song.json"}


def two_bar_song(part, variation):
    return {"id": "variation_review", "tempo": 240, "key": "C major", "meter": "4/4", "form": ["A", "B"],
            "sections": {"A": {"bars": 1, "chords": "I"}, "B": {"bars": 1, "chords": "V"}},
            "master": {"reverb": "none"}, "parts": [part], "variation": variation}


def test_selected_absolute_part_keeps_metadata_aligned_with_events(tmp_path):
    part = {"name": "abs", "instrument": "nylon_guitar", "bars": ["C4:4", "C4+E4:4"], "sections": ["B"],
            "humanize": .2, "reverb": 0}
    song = load(tmp_path, two_bar_song(part, [{"section": "B", "part": "abs", "do": "octave_up"}]))
    compiled = render.compile_song(song)
    assert compiled["notes"]["abs"] == [(4.0, [72, 76], 4.0, compiled["notes"]["abs"][0][3])]
    assert [len(m["tones"]) for m in compiled["event_metadata"]["abs"]] == [2]
    assert render.render_part(song["parts"][0], song).any()


def test_degree_part_octave_is_range_checked_after_resolver(tmp_path):
    part = {"name": "mel", "role": "melody", "instrument": "square", "grid": "1/4", "octave": 1,
            "phrases": {"A": "1,,,,,, - - -", "B": ". . . ."}, "reverb": 0}
    song = load(tmp_path, two_bar_song(part, [{"section": "A", "part": "mel", "do": "octave_up"}]))
    assert render.compile_song(song)["notes"]["mel"][0][1] == [12]


def test_empty_variation_on_legacy_song_keeps_legacy_path(tmp_path):
    raw = json.loads((render.SONGS / "proto_test" / "song.json").read_text(encoding="utf-8"))
    plain = load(tmp_path, raw)
    varied = load(tmp_path, dict(raw, variation=[]))
    for a, b in zip(plain["parts"], varied["parts"], strict=True):
        assert render.part_hash(a, plain) == render.part_hash(b, varied)


def test_empty_variation_on_structured_song_keeps_old_meter_support(tmp_path):
    raw = {"id": "five", "tempo": 120, "key": "C major", "meter": "5/8", "form": ["A"],
           "sections": {"A": {"bars": 1, "chords": "I"}}, "master": {"reverb": "none"},
           "parts": [{"name": "lead", "instrument": "square", "bars": ["C4:2.5"], "reverb": 0}]}
    plain = load(tmp_path, raw)
    varied = load(tmp_path, dict(raw, variation=[]))
    assert render.compile_song(plain) == render.compile_song(varied)
    assert render.part_hash(plain["parts"][0], plain) == render.part_hash(varied["parts"][0], varied)


def test_replaced_source_instrument_is_never_loaded(tmp_path, monkeypatch):
    part = {"name": "lead", "instrument": "piano", "bars": ["C4:4", "C4:4"], "reverb": 0}
    song = load(tmp_path, dict(two_bar_song(part, []), form=["A", "A"],
                               variation=[{"section": "A", "part": "lead", "do": "instrument", "instrument": "bass"}]))
    real = render.get_instrument
    monkeypatch.setattr(render, "get_instrument", lambda name: pytest.fail("未使用のpianoを読み込んだ") if name == "piano" else real(name))
    assert render.render_part(song["parts"][0], song).any()
