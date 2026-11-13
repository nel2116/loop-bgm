"""変化の依存順、描画一回、旧cache互換を数値で検査する。"""

import copy
import json

import numpy as np
import pytest

from bgm import render, synth


def design(meter="4/4"):
    beats = 4 if meter == "4/4" else 3
    return {"id": "variation_test", "tempo": 240, "key": "C major", "meter": meter,
            "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": 2, "chords": "Iadd9/3 iii V | I"}, "B": {"bars": 2, "chords": "iv | V"}},
            "master": {"reverb": "none"},
            "parts": [
                {"name": "copy", "role": "arrange", "copy": "melody", "octave": -1, "humanize": .2, "reverb": 0},
                {"name": "counter", "role": "arrange", "accent": "counter", "source": "melody", "instrument": "kalimba",
                 "humanize": .2, "reverb": 0},
                {"name": "melody", "role": "melody", "instrument": "nylon_guitar",
                 "bars": [f"C4+E4:{2 * beats}"], "humanize": .2, "reverb": 0},
                {"name": "arp", "role": "chords", "style": "arpeggio_up", "instrument": "kalimba",
                 "humanize": .2, "reverb": 0},
                {"name": "drums", "type": "drums", "bars": [{"noise_hit": "x..."}], "humanize": .2, "reverb": 0}]}


def load(tmp_path, song):
    (tmp_path / "song.json").write_text(json.dumps(song), encoding="utf-8")
    return render.load_song(str(tmp_path))[1]


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
def test_source_octave_before_copy_and_rest_before_counter(tmp_path, meter):
    song = design(meter)
    song["variation"] = [{"section": "A", "part": "melody", "do": "octave_up"},
                         {"section": "B", "part": "melody", "do": "rest"}]
    song = load(tmp_path, song)
    original = copy.deepcopy(song)
    compiled = render.compile_song(song)
    assert compiled["notes"]["melody"][0][1] == [72, 76]
    assert compiled["notes"]["copy"][0][1] == [60, 64]
    assert all(not 2 * compiled["beats_per_bar"] <= e[0] < 4 * compiled["beats_per_bar"]
               for e in compiled["notes"]["melody"])
    assert any(e[0] == 2 * compiled["beats_per_bar"] for e in compiled["notes"]["counter"])
    assert song == original


@pytest.mark.parametrize("variation", [[], [{"part": "drums", "every": 99, "do": "fill_last_bar"}],
                                      [{"section": "B", "part": "melody", "do": "octave_up"}]])
def test_empty_effect_retains_exact_compiled_hash_and_audio(tmp_path, variation):
    source = design()
    source["parts"][2]["sections"] = ["A"]
    plain = load(tmp_path, source)
    varied = load(tmp_path, dict(source, variation=variation))
    assert render.compile_song(plain) == render.compile_song(varied)
    for part in varied["parts"]:
        assert render.part_hash(part, plain) == render.part_hash(part, varied)
        assert np.array_equal(render.render_part(part, plain), render.render_part(part, varied))


@pytest.mark.parametrize("meter,period", [("4/4", 3), ("3/4", 4), ("6/8", 4)])
def test_period_current_full_voicing_and_true_phase_through_gaps(tmp_path, meter, period):
    song = design(meter)
    song["parts"][3].update(sections=["A", "A'"], octave=1, transpose=2)
    song["variation"] = [{"part": "arp", "do": "period", "beats": period}]
    compiled = render.compile_song(load(tmp_path, song))
    for event, meta in zip(compiled["notes"]["arp"], compiled["event_metadata"]["arp"], strict=True):
        chord = compiled["harmony"][meta["harmony_index"]]
        assert event[1] == [chord["pitches"][meta["slot"]] + 14]
        assert event[0] == pytest.approx(meta["cycle"] * period + meta["slot"] * period / len(chord["pitches"]))
    assert len({e[0] for e in compiled["notes"]["arp"]}) == len(compiled["notes"]["arp"])


def test_instrument_timeline_inherits_only_when_absent_and_keeps_source_dsp_out(tmp_path):
    song = design()
    song["parts"].insert(0, {"name": "explicit", "role": "arrange", "copy": "melody", "instrument": "square"})
    song["variation"] = [{"section": "B", "part": "melody", "do": "instrument", "instrument": "bass"}]
    song = load(tmp_path, song)
    compiled = render.compile_song(song)
    for name in ("melody", "copy"):
        assert next(m["instrument"] for e, m in zip(compiled["notes"][name], compiled["event_metadata"][name], strict=True)
                    if e[0] == 8) == "bass"
    assert "explicit" not in compiled["variation_parts"]
    hashes = {p["name"]: render.part_hash(p, song) for p in song["parts"]}
    changed = copy.deepcopy(song)
    changed["parts"][3].update(volume=.2, pan=.8, gate=.1, strum=.13, reverb=.7, humanize=.5)
    assert render.part_hash(changed["parts"][1], changed) == hashes["copy"]


def test_removed_events_preserve_exact_original_rng_draws(tmp_path, monkeypatch):
    song = design()
    song["variation"] = [{"section": "B", "part": "melody", "do": "rest"}]
    varied = load(tmp_path, song)
    plain = load(tmp_path, {k: v for k, v in song.items() if k != "variation"})
    calls = []
    placements = []
    monkeypatch.setattr(synth, "render_pitched", lambda voice, midi, velocity, duration, *, seed:
                        calls.append((voice, midi, velocity, duration, seed)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: placements.append(start) or buf)
    part = song["parts"][2]
    render.render_part(part, plain)
    before, onsets = list(calls), list(placements)
    calls.clear()
    placements.clear()
    render.render_part(part, varied)
    assert calls == before[:2] + before[4:]
    assert placements == onsets[:2] + onsets[4:]


@pytest.mark.parametrize("variation", [None, {}, [{"section": "A", "part": "melody", "do": "unknown"}],
                                      [{"part": "arp", "do": "period", "beats": None}],
                                      [{"section": "B", "part": "melody", "do": "instrument", "instrument": "bogus"}]])
def test_invalid_variation_fails_load_before_audio(tmp_path, monkeypatch, variation):
    song = design()
    song["variation"] = variation
    monkeypatch.setattr(render, "get_instrument", lambda *_: pytest.fail("音源アクセス"))
    with pytest.raises(render.SongError, match="小節"):
        load(tmp_path, song)
    assert not (tmp_path / "stems").exists()


def test_raw_compile_song_treats_empty_variation_as_absent():
    song = {"id": "five_eight", "tempo": 120, "key": "C major", "meter": "5/8", "form": ["A"],
            "sections": {"A": {"bars": 1, "chords": "I"}}, "master": {"reverb": "none"},
            "parts": [{"name": "lead", "instrument": "square", "bars": ["C4:2.5"]}]}
    assert render.compile_song(dict(song, variation=[])) == render.compile_song(song)


def test_rest_cuts_only_the_end_and_keeps_negative_strum_onset(tmp_path, monkeypatch):
    song = {"id": "rest_strum", "tempo": 60, "key": "C major", "meter": "4/4", "form": ["A", "B"],
            "sections": {"A": {"bars": 1, "chords": "I"}, "B": {"bars": 1, "chords": "V"}},
            "master": {"reverb": "none"},
            "parts": [{"name": "held", "instrument": "nylon_guitar", "bars": ["r:1 C4+E4:7"],
                       "humanize": 0, "strum": -0.02, "reverb": 0}]}
    plain = load(tmp_path, song)
    varied = load(tmp_path, dict(song, variation=[{"section": "B", "part": "held", "do": "rest"}]))
    calls = []
    monkeypatch.setattr(synth, "render_pitched", lambda voice, midi, velocity, duration, *, seed:
                        calls.append((midi, duration)) or np.zeros((1, 2), np.float32))
    placements = []
    monkeypatch.setattr(render, "place", lambda buf, audio, start: placements.append(start) or buf)
    render.render_part(plain["parts"][0], plain)
    before = list(placements)
    placements.clear()
    calls.clear()
    render.render_part(varied["parts"][0], varied)
    assert placements == before
    assert placements[1] < render.SR
    # 持続はBの頭(4秒)より前で終わる。2音目の開始は負のstrumで0.98秒のまま。
    assert all(p / render.SR + d <= 4 + 1e-9 for p, (_, d) in zip(placements, calls, strict=True))
    assert [d for _, d in calls] == [3.0, 3.0]


def test_empty_period_selection_still_validates_generator_settings(tmp_path):
    song = design()
    song["parts"][3].update(sections=[], kit=[])
    song["variation"] = [{"part": "arp", "do": "period", "beats": 3}]
    with pytest.raises(render.SongError, match="kit"):
        load(tmp_path, song)


def test_degree_pitch_out_of_range_before_variation_is_rejected_with_explanation(tmp_path):
    # variationを外した曲も有効であることが契約。octave_upで範囲内に戻っても変化前の音高で拒否する。
    song = {"id": "pre_variation_range", "tempo": 120, "key": "C major", "meter": "4/4", "form": ["A"],
            "sections": {"A": {"bars": 1, "chords": "I"}}, "master": {"reverb": "none"},
            "parts": [{"name": "lead", "instrument": "square", "grid": "1/4", "phrases": {"A": "1,,,,,, - - -"}}]}
    with pytest.raises(render.SongError) as plain:
        load(tmp_path, song)
    assert "variation" not in str(plain.value)
    with pytest.raises(render.SongError, match=r"\[lead\] 1番目の小節: .*範囲.*variation を適用する前の音高です"):
        load(tmp_path, dict(song, variation=[{"section": "A", "part": "lead", "do": "octave_up"}]))
    other = copy.deepcopy(song)
    other["parts"].append({"name": "other", "instrument": "square", "grid": "1/4", "phrases": {"A": "1 - - -"}})
    with pytest.raises(render.SongError) as unrelated:
        load(tmp_path, dict(other, variation=[{"section": "A", "part": "other", "do": "octave_up"}]))
    assert str(unrelated.value) == str(plain.value)
