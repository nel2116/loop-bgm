"""構造と度数を実際の読み込み・キャッシュ・音声へ接続する検証。"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from bgm import render

SAMPLE = Path(__file__).resolve().parents[1] / "songs/phase1_degrees/song.json"


@pytest.fixture
def design():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def write_song(folder, song):
    (folder / "song.json").write_text(json.dumps(song), encoding="utf-8")
    return str(folder)


def test_compilation_preserves_input_and_exposes_notes_harmony(design):
    before = copy.deepcopy(design)
    compiled = render.compile_song(design)
    assert design == before
    assert compiled["bars"] == 4
    assert [o["start_bar"] for o in compiled["occurrences"]] == [1, 3]
    assert compiled["notes"]["melody"][1] == (1, [64], 1, 90)
    assert compiled["harmony"][0]["pitches"] == [48, 52, 55]
    assert compiled["harmony"][-1]["bar"] == 4
    assert compiled["harmony"][-1]["source"] == "B"
    # ループで同じ部分が続かない(#74): 末尾の B(ii V7)から先頭の A(I)へ戻る。
    form = design["form"]
    assert all(form[i] != form[(i + 1) % len(form)] for i in range(len(form)))


@pytest.mark.parametrize("meter", ["3/4", "6/8"])
def test_quarter_note_timing_and_primed_selection(tmp_path, design, meter):
    design["meter"] = meter
    design["form"] = ["A", "A'", "B"]
    design["parts"][0].update(sections=["A'"], phrases={"A": "1 3 5 | 4 3 2"})
    design["parts"][1]["bars"] = ["C3:3"]
    _, song = render.load_song(write_song(tmp_path, design))
    compiled = render.compile_song(song)
    assert song["beats_per_bar"] == 3
    assert render.song_seconds(song) == 9
    assert compiled["notes"]["melody"][0] == (6, [60], 1, 90)
    assert [chord["bar"] for chord in compiled["harmony"]] == [1, 2, 2, 3, 4, 4, 5, 6, 6]


def test_optional_legacy_key_remains_uninterpreted(tmp_path):
    legacy = {"tempo": 120, "bars": 2, "key": "legacy annotation",
              "parts": [{"name": "absolute", "instrument": "square", "bars": ["C4:4"]}]}
    _, song = render.load_song(write_song(tmp_path, legacy))
    assert render.parse_note_bars(song["parts"][0], song) == [(0, [60], 4, 90), (4, [60], 4, 90)]


@pytest.mark.slow
def test_key_only_change_and_two_force_renders(tmp_path, design):
    ref = write_song(tmp_path, design)
    _, major = render.load_song(ref)
    major_notes = render.compile_song(major)["notes"]
    out = render.render_song(ref, force=True, mp3=False, log=lambda *_: None)
    first = sf.read(out, dtype="float32")[0]
    stems = {p["name"]: sf.read(tmp_path / "stems" / f"{p['name']}.wav")[0] for p in design["parts"]}
    render.render_song(ref, force=True, mp3=False, log=lambda *_: None)
    assert np.array_equal(first, sf.read(out, dtype="float32")[0])
    for name, audio in stems.items():
        assert np.array_equal(audio, sf.read(tmp_path / "stems" / f"{name}.wav")[0])
    assert render.check_loop(first)[0]
    design["key"] = "C minor"
    write_song(tmp_path, design)
    _, minor = render.load_song(ref)
    minor_notes = render.compile_song(minor)["notes"]
    assert major_notes["melody"][1][1] == [64]
    assert minor_notes["melody"][1][1] == [63]
    assert major_notes["absolute"] == minor_notes["absolute"]
    render.render_song(ref, mp3=False, log=lambda *_: None)
    assert not np.array_equal(first, sf.read(out, dtype="float32")[0])
    assert np.array_equal(stems["absolute"], sf.read(tmp_path / "stems/absolute.wav")[0])
    assert render.check_loop(sf.read(out, dtype="float32")[0])[0]


@pytest.mark.parametrize("field", ["key", "form", "phrases", "chords", "meter"])
def test_cache_tracks_structure_and_compiled_events(tmp_path, design, field):
    ref = write_song(tmp_path, design)
    _, original = render.load_song(ref)
    old = render.part_hash(original["parts"][0], original)
    if field == "key":
        design["key"] = "C minor"
    elif field == "form":
        design["form"] = ["B", "A", "A"]
    elif field == "phrases":
        design["parts"][0]["phrases"]["A"] = "1 2 5 3 | 4 3 2 1"
    elif field == "chords":
        design["sections"]["A"]["chords"] = "V | IV V"
    else:
        design["meter"] = "2/2"
    write_song(tmp_path, design)
    _, changed = render.load_song(ref)
    assert render.part_hash(changed["parts"][0], changed) != old
    changed["parts"][0].update(volume=0.2, pan=0.3, mute=True, solo=True, note="説明")
    mixed = render.part_hash(changed["parts"][0], changed)
    for key in render.MIX_ONLY_KEYS:
        changed["parts"][0].pop(key, None)
    assert render.part_hash(changed["parts"][0], changed) == mixed


def invalid_cases():
    return [
        ("missing", "key", None, "key"),
        ("missing", "meter", None, "meter"),
        ("missing", "form", None, "form"),
        ("missing", "sections", None, "sections"),
        ("song", "bars", 9, "競合"),
        ("song", "beats_per_bar", 3, "競合"),
        ("song", "meter", "9" * 400 + "/1", "有限数"),
        ("song", "key", "Q major", "調"),
        ("part", "bars", ["C4:4"], "[melody]"),
        ("part", "grid", "1/3", "[melody]"),
        ("part", "phrases", {"A": "1 3 . - | 4 3 2 1", "B": "6 5 3 1 | 2 5 7 5"}, "[melody] 1番目の小節"),
        ("part", "phrases", {"A": "1 C4 5 3 | 4 3 2 1", "B": "6 5 3 1 | 2 5 7 5"}, "[melody] 1番目の小節"),
        ("harmony", "chords", "I | nonsense", "[harmony] 2番目の小節"),
        ("absolute", "bars", ["1:4"], "[absolute] 1番目の小節"),
    ]


@pytest.mark.parametrize(("scope", "field", "value", "message"), invalid_cases())
def test_invalid_inputs_precede_all_render_side_effects(tmp_path, design, monkeypatch, scope, field, value, message):
    target = {"song": design, "part": design["parts"][0], "harmony": design["sections"]["A"],
              "absolute": design["parts"][1], "missing": design}[scope]
    if scope == "missing":
        target.pop(field)
    else:
        target[field] = value
    ref = write_song(tmp_path, design)

    def forbidden(*args, **kwargs):
        pytest.fail("不正な曲が音源またはキャッシュへ到達しました")

    monkeypatch.setattr(render, "get_instrument", forbidden)
    monkeypatch.setattr(render, "get_drum", forbidden)
    monkeypatch.setattr(render, "part_hash", forbidden)
    with pytest.raises(render.SongError) as error:
        render.render_song(ref, mp3=False)
    assert message in str(error.value)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.json"]


@pytest.mark.parametrize("command", ["render", "listen"])
@pytest.mark.parametrize("scope", ["melody", "harmony"])
def test_invalid_cli_has_japanese_part_bar_without_traceback(tmp_path, design, command, scope):
    if scope == "melody":
        design["parts"][0]["phrases"]["B"] = "1 2 3 WRONG | 1 2 3 4"
    else:
        design["sections"]["B"]["chords"] = "WRONG | V"
    result = subprocess.run([sys.executable, "-m", "bgm", command, write_song(tmp_path, design),
                             *(["--no-mp3"] if command == "render" else [])],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert f"[{scope}] 3番目の小節" in result.stderr
