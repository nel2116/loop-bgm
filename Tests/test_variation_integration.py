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
