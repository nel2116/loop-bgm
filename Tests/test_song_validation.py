# 現行 song.json の入力検証。外部音源は使用しない。
import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from bgm.render import SongError, load_song, render_part

BASE = {"tempo": 120, "bars": 2, "master": {"reverb": "none"},
        "parts": [{"name": "lead", "instrument": "square", "bars": ["C4:4"]}]}
BAD_TYPES = [None, True, "120", [], {}]


def write_song(tmp_path, data):
    path = tmp_path / "song.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def changed(scope, key, value):
    data = copy.deepcopy(BASE)
    target = data if scope == "song" else data["master"] if scope == "master" else data["parts"][0]
    target[key] = value
    return data


CASES = [(changed("part", "bars", [{}]), "[lead] 1番目の小節")]
for field in ("tempo", "bars", "beats_per_bar", "swing", "swing_unit"):
    for value in [*BAD_TYPES, float("nan"), float("inf"), -float("inf")]:
        CASES.append((changed("song", field, value), field))
for field, values in {"tempo": [0, -1], "bars": [0, -1, 1.5], "beats_per_bar": [0, -1], "swing_unit": [0, -1]}.items():
    CASES.extend((changed("song", field, value), field) for value in values)
for field in ("volume", "pan", "velocity", "humanize", "reverb", "gate", "strum", "transpose", "octave"):
    CASES.extend((changed("part", field, value), f"[lead] {field}") for value in [*BAD_TYPES, float("nan"), float("inf")])
CASES.append((changed("part", "humanize", -1), "[lead] humanize"))
CASES.extend((changed("master", "gain_db", value), "master.gain_db") for value in [*BAD_TYPES, float("inf")])
for field in ("loop",):
    CASES.extend((changed("song", field, value), field) for value in [0, 1, "true", [], {}])
for field in ("mute", "solo"):
    CASES.extend((changed("part", field, value), f"[lead] {field}") for value in [0, 1, "true", [], {}])
for value in [None, [], {}, 1, "missing"]:
    CASES.append((changed("part", "instrument", value), "[lead] instrument"))
for value in [False, 1, [], {}]:
    CASES.append((changed("part", "type", value), "[lead] type"))
for value in [[], {}, 1, False]:
    CASES.append((changed("master", "reverb", value), "master.reverb"))
for value in [True, 1, {}, "C4:4", [None], [1], [[]], [True]]:
    CASES.append((changed("part", "bars", value), "[lead]"))
for token in ["C4:1/0", "C4:1..0", "C4:0", "C4:0/1", "C4:4@" + "9" * 400, "C999999:4", "C-999999:4", "C4:3"]:
    CASES.append((changed("part", "bars", [token]), "[lead] 1番目の小節"))
CASES.append((changed("song", "parts", []), "parts"))
CASES.extend((changed("song", key, value), key) for key, value in [
    ("tempo", 1e-320), ("tempo", 1e308), ("bars", 10 ** 400), ("beats_per_bar", 1e308)])
data = changed("song", "swing_unit", 1e-320)
data["swing"] = 1
CASES.append((data, "swing"))
SWING_OVERFLOW_INDEX = len(CASES)
data = changed("song", "swing", 10 ** 200)
data["swing_unit"] = 10 ** 200
CASES.append((data, "swing / swing_unit"))
data = changed("part", "bars", ["C4:" + "9" * 308])
data["parts"][0]["gate"] = 100
CASES.append((data, "[lead] 1番目の小節"))
for field, value in [("voices", None), ("voices", []), ("voices", {"kick": []}),
                     ("voices", {"kick": {"pan": []}}), ("voices", {"kick": {"volume": float("nan")}}),
                     ("bars", ["x..."]), ("bars", [{"kick": None}]), ("bars", [{"kick": 1}]),
                     ("bars", [{"kick": "?"}]), ("bars", [{"unknown": "x"}])]:
    data = copy.deepcopy(BASE)
    data["parts"] = [{"name": "kit", "type": "drums", "bars": [{"kick": "x..."}]}]
    data["parts"][0][field] = value
    CASES.append((data, "[kit]"))


@pytest.mark.parametrize(("data", "location"), CASES)
def test_invalid_song_reports_location(tmp_path, data, location):
    with pytest.raises(SongError) as error:
        load_song(str(write_song(tmp_path, data)))
    assert location in str(error.value)


def test_unknown_instrument_does_not_suggest_an_unavailable_command(tmp_path):
    with pytest.raises(SongError) as error:
        load_song(str(write_song(tmp_path, changed("part", "instrument", "unknown"))))
    assert "[lead] instrument に存在する楽器名が必要です" == str(error.value)


@pytest.mark.parametrize("command", ["listen", "render"])
@pytest.mark.parametrize("index", [0, 1, SWING_OVERFLOW_INDEX, len(CASES) - 1, len(CASES) - 3])
def test_cli_rejects_nested_and_scalar_errors(tmp_path, command, index):
    data, location = CASES[index]
    path = write_song(tmp_path, data)
    result = subprocess.run([sys.executable, "-m", "bgm", command, str(path),
                             *(["--no-mp3"] if command == "render" else [])],
                            capture_output=True, text=True, encoding="utf-8", timeout=15,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 1
    assert location in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "stems").exists()


@pytest.mark.parametrize("bars", [None, [], "", [""], ["-"], ["r:4"]])
def test_empty_note_bars_keep_silence(tmp_path, bars):
    data = changed("part", "bars", bars)
    _, song = load_song(str(write_song(tmp_path, data)))
    assert not np.any(render_part(song["parts"][0], song))


def test_omissions_null_flags_and_voice_settings_keep_existing_meanings(tmp_path):
    data = copy.deepcopy(BASE)
    data["loop"] = None
    data["master"]["reverb"] = None
    data["parts"] = [{"name": "kit", "type": "drums", "mute": None, "solo": None,
                      "bars": [{"kick": "x...", "hat": ""}, {}], "voices": {"kick": None}}]
    _, song = load_song(str(write_song(tmp_path, data)))
    actual = render_part(song["parts"][0], song)
    del song["parts"][0]["voices"]
    np.testing.assert_array_equal(actual, render_part(song["parts"][0], song))


def test_defaults_do_not_change_audio(tmp_path):
    data = copy.deepcopy(BASE)
    _, song = load_song(str(write_song(tmp_path, data)))
    expected = {**data, "beats_per_bar": 4, "swing": 0, "swing_unit": 0.5, "loop": True,
                "master": {"reverb": "none", "gain_db": 0}}
    np.testing.assert_array_equal(render_part(song["parts"][0], song), render_part(data["parts"][0], expected))


def test_unused_extra_drum_bar_is_still_validated(tmp_path):
    data = copy.deepcopy(BASE)
    data["bars"] = 1
    data["parts"] = [{"name": "kit", "type": "drums", "bars": [{}, {"kick": None}]}]
    with pytest.raises(SongError, match="2番目の小節"):
        load_song(str(write_song(tmp_path, data)))


def test_existing_clamps_and_unused_metadata_are_preserved(tmp_path):
    data = copy.deepcopy(BASE)
    data["title"] = {"unused": True}
    data["master"]["reverb"] = "unknown-is-dry"
    data["parts"][0].update(type="notes", velocity=999, pan=10, gate=-1, reverb=-1,
                             transpose=0.5, octave=-0.5, strum=-0.01, note={"unused": True})
    _, song = load_song(str(write_song(tmp_path, data)))
    assert song["parts"] == data["parts"]
    assert np.isfinite(render_part(song["parts"][0], song)).all()


def test_empty_unused_drum_voice_and_missing_bars_remain_valid(tmp_path):
    data = copy.deepcopy(BASE)
    data["parts"] = [{"name": "kit", "type": "drums", "bars": [{"unused": ".-_ |"}]},
                     {"name": "lead", "instrument": "square"}]
    _, song = load_song(str(write_song(tmp_path, data)))
    for part in song["parts"]:
        assert not np.any(render_part(part, song))
