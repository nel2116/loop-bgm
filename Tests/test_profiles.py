"""song.json の usage と用途ごとの方針（bgm/profiles.py）。値は docs/spec.md 5.4。"""

import json

import pytest

from bgm import profiles, render

BASE = {"tempo": 120, "bars": 1, "parts": [{"name": "lead", "instrument": "square", "bars": ["C4:4"]}]}


def load(tmp_path, **fields):
    (tmp_path / "song.json").write_text(json.dumps({**BASE, **fields}), encoding="utf-8")
    return render.load_song(str(tmp_path))[1]


def test_profile_table_matches_spec():
    assert {name: (p.lufs, p.voice_band, p.loop_seconds) for name, p in profiles.PROFILES.items()} == {
        "video": (-16.0, True, (60, 120)),
        "game": (-16.0, False, (60, 180)),
        "trpg": (-20.0, True, (120, 300)),
    }


@pytest.mark.parametrize("usage", ["video", "game", "trpg"])
def test_valid_usage_resolves(tmp_path, usage):
    song = load(tmp_path, usage=usage)
    assert profiles.resolve(song).name == usage


def test_missing_usage_is_a_japanese_error(tmp_path):
    with pytest.raises(render.SongError, match="usage がありません"):
        load(tmp_path)


@pytest.mark.parametrize("usage", ["movie", "", 3, None, ["video"]])
def test_unknown_usage_is_a_japanese_error(tmp_path, usage):
    with pytest.raises(render.SongError, match="video / game / trpg のどれか"):
        load(tmp_path, usage=usage)
