"""生成伴奏の共通検証、境界、従来経路を確認する。"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from bgm import render

EXAMPLE = Path(__file__).resolve().parents[1] / "songs/phase1_accompaniment/song.json"


@pytest.fixture
def design():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def write_song(tmp_path, design):
    (tmp_path / "song.json").write_text(json.dumps(design), encoding="utf-8")
    return str(tmp_path)


def test_compiled_events_and_input_preservation(design):
    original = copy.deepcopy(design)
    result = render.compile_song(design)
    assert design == original
    assert set(result["notes"]) == {"melody", "bass", "chords", "absolute"}
    assert set(result["rhythm"]) == {"rhythm", "direct_drums"}
    assert [o["name"] for o in result["occurrences"]] == ["A", "B", "A"]
    assert (6, [43], 1.8, 90) in result["notes"]["bass"]
    assert result["rhythm"]["direct_drums"][0] == (2, "rim", 95)
    assert render.parse_drum_bars(design["parts"][3], dict(design, bars=6, beats_per_bar=4)) == result["rhythm"]["rhythm"]


@pytest.mark.parametrize("change", [
    {"style": "unknown"}, {"bars": []}, {"phrases": {}}, {"grid": None}, {"groove": "march"},
    {"role": "melody"}, {"type": "drums"}, {"octave": True}, {"transpose": 0.5}, {"sections": ["unknown"]},
])
def test_invalid_generated_notes_fail_before_side_effects(tmp_path, monkeypatch, design, change):
    design["parts"][1].update(change)
    assert_early_error(tmp_path, monkeypatch, design)


@pytest.mark.parametrize("change", [
    {"groove": "unknown"}, {"style": "pad"}, {"bars": []}, {"phrases": {}}, {"grid": None},
    {"role": "bass"}, {"type": "notes"}, {"kit": ["unknown"]}, {"voices": {"unknown": {}}},
])
def test_invalid_generated_drums_fail_before_side_effects(tmp_path, monkeypatch, design, change):
    design["parts"][3].update(change)
    assert_early_error(tmp_path, monkeypatch, design)


@pytest.mark.parametrize("change", [{"bars": [{"bad": "x..."}]}])
def test_unknown_direct_drum_names_fail_early(tmp_path, monkeypatch, design, change):
    design["parts"][-1].update(change)
    assert_early_error(tmp_path, monkeypatch, design)


def assert_early_error(tmp_path, monkeypatch, design):
    ref = write_song(tmp_path, design)

    def forbidden(*args, **kwargs):
        pytest.fail("検証前に音源またはキャッシュへアクセスした")

    monkeypatch.setattr(render, "get_instrument", forbidden)
    monkeypatch.setattr(render, "get_drum", forbidden)
    monkeypatch.setattr(render, "part_hash", forbidden)
    with pytest.raises(render.SongError, match=r"\[.*\]"):
        render.render_song(ref, mp3=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.json"]


@pytest.mark.parametrize("command", ["render", "listen"])
@pytest.mark.parametrize("invalid", ["meter", "voice", "style", "groove", "conflict"])
def test_cli_validation_shared_and_japanese(tmp_path, design, command, invalid):
    if invalid == "meter":
        design["meter"] = "5/4"
        design["parts"] = design["parts"][1:4]
    elif invalid == "voice":
        design["parts"][3]["voices"] = {"bad": {}}
    elif invalid == "style":
        design["parts"][1]["style"] = "bad"
    elif invalid == "groove":
        design["parts"][3]["groove"] = "bad"
    else:
        design["parts"][1]["bars"] = []
    ref = write_song(tmp_path, design)
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "bgm", command, ref], capture_output=True, encoding="utf-8")
    assert p.returncode != 0
    assert "Traceback" not in p.stdout + p.stderr
    assert "小節" in p.stdout + p.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.json"]


@pytest.mark.parametrize("onset,duration,expected", [
    (-0.1, 9, (0, 2)), (1.99, .02, (1.99, .01)), (2, 1, (2, 0)), (3, 1, (3, -1)),
])
def test_window_clips_without_reextending_short_notes(design, onset, duration, expected):
    compiled = render.compile_song(design)
    actual = render._generated_window(0, onset, duration, compiled, .5)
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize("gate,strum,swing,humanize", [(4, .99, 0, 0), (3, -.3, -.8, 2), (2, .015, .6, .2)])
def test_dsp_calls_obey_harmony_and_occurrence_windows(tmp_path, monkeypatch, design, gate, strum, swing, humanize):
    part = design["parts"][2]
    part.update(gate=gate, strum=strum, humanize=humanize, sections=["B"])
    design["swing"] = swing
    _, song = render.load_song(write_song(tmp_path, design))
    calls, placements = [], []

    def voice(midi, velocity, duration):
        calls.append(duration)
        return np.zeros((1, 2), np.float32)

    original_place = render.place

    def placed(buffer, audio, start):
        placements.append(start / render.SR)
        return original_place(buffer, audio, start)

    monkeypatch.setattr(render, "get_instrument", lambda *_: voice)
    monkeypatch.setattr(render, "place", placed)
    render.render_part(part, song)
    seconds = 60 / song["tempo"]
    assert calls
    for onset, duration in zip(placements, calls, strict=True):
        assert duration > 0
        assert 8 * seconds - 1 / render.SR <= onset < 16 * seconds
        boundary = 12 * seconds if onset < 12 * seconds - 1 / render.SR else 16 * seconds
        assert onset + duration <= boundary + 1 / render.SR


@pytest.mark.parametrize("role,style,tones", [("bass", "root_whole", 1), ("chords", "pad", 3)])
def test_non_grid_harmony_boundaries_and_song_end(tmp_path, monkeypatch, design, role, style, tones):
    design.update(form=["A"], sections={"A": {"bars": 1, "chords": "I ii V"}}, swing=.7)
    part = {"name": "generated", "role": role, "style": style, "instrument": "square",
            "humanize": .5, "gate": 8, "strum": .06, "reverb": 0}
    design["parts"] = [part]
    _, song = render.load_song(write_song(tmp_path, design))
    durations, onsets = [], []

    def voice(midi, velocity, duration):
        durations.append(duration)
        return np.zeros((1, 2), np.float32)

    def placed(buffer, audio, start):
        onsets.append(start / render.SR)
        return buffer

    monkeypatch.setattr(render, "get_instrument", lambda *_: voice)
    monkeypatch.setattr(render, "place", placed)
    render.render_part(part, song)
    assert len(durations) == 3 * tones
    span = (4 / 3) * 60 / song["tempo"]
    for index, (onset, duration) in enumerate(zip(onsets, durations, strict=True)):
        chord_index = index // tones
        assert chord_index * span - 1 / render.SR <= onset < (chord_index + 1) * span
        assert 0 < duration
        assert onset + duration <= (chord_index + 1) * span + 1 / render.SR


def test_key_changes_generated_pitches_but_preserves_absolute_and_direct_drums(design):
    major = render.compile_song(design)
    design["key"] = "C minor"
    minor = render.compile_song(design)
    for name in ("melody", "bass", "chords"):
        assert major["notes"][name] != minor["notes"][name]
    assert major["notes"]["absolute"] == minor["notes"]["absolute"]
    assert major["rhythm"] == minor["rhythm"]


def test_skipped_strum_notes_keep_original_chord_seed_index(tmp_path, monkeypatch, design):
    from bgm import synth

    part = design["parts"][2]
    part.update(instrument="nylon_guitar", strum=-.2, humanize=0)
    _, song = render.load_song(write_song(tmp_path, design))
    calls = []
    monkeypatch.setattr(render, "parse_note_bars", lambda *_: [(.5, [60, 64, 67], .4, 90)])
    monkeypatch.setattr(render, "_swing", lambda *_: 4.92)
    monkeypatch.setattr(render, "get_instrument", lambda *_: None)

    def pitched(voice, midi, velocity, duration, *, seed):
        calls.append((midi, duration, seed))
        return np.zeros((1, 2), np.float32)

    monkeypatch.setattr(synth, "render_pitched", pitched)
    render.render_part(part, song)
    # 144BPMでは終端1.666...秒、onset2.05秒から負strumで最後の音だけ区間内に入る。
    assert len(calls) == 1
    assert calls[0][0] == 67
    assert calls[0][2] == render._synth_seed(part["name"], "nylon_guitar", .5, 0, 2, 67)
    assert 0 < calls[0][1] < .02


@pytest.mark.parametrize("role,type_", [("rhythm", None), ("rhythm", "drums"), (None, "drums")])
def test_approved_groove_routing(tmp_path, design, role, type_):
    part = design["parts"][3]
    part.pop("role", None)
    if role:
        part["role"] = role
    if type_:
        part["type"] = type_
    _, song = render.load_song(write_song(tmp_path, design))
    assert render.compile_song(song)["rhythm"]["rhythm"]


@pytest.mark.parametrize("field", ["key", "form", "chords", "style", "groove", "volume", "pan"])
def test_hash_dependencies(tmp_path, design, field):
    _, before = render.load_song(write_song(tmp_path, design))
    old = {p["name"]: render.part_hash(p, before) for p in before["parts"]}
    if field == "key":
        design["key"] = "C minor"
    elif field == "form":
        design["form"] = ["B", "A", "A"]
    elif field == "chords":
        design["sections"]["A"]["chords"] = "vi | IV V"
    elif field == "style":
        design["parts"][1]["style"] = "root_quarter"
    elif field == "groove":
        design["parts"][3]["groove"] = "march"
    else:
        for part in design["parts"]:
            part[field] = .2
    _, after = render.load_song(write_song(tmp_path, design))
    new = {p["name"]: render.part_hash(p, after) for p in after["parts"]}
    if field in ("volume", "pan"):
        assert old == new
    elif field in ("style", "groove"):
        changed = "bass" if field == "style" else "rhythm"
        assert {name for name in old if old[name] != new[name]} == {changed}
    else:
        assert all(old[name] != new[name] for name in ("melody", "bass", "chords"))


