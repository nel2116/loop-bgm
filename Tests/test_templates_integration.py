"""実在の templates/*.json を bgm/templates.py で読み、bgm new の雛形と見本曲を確かめる統合テスト。

音源は使わない（load_song / compile_song とファイルの比較だけ）。
"""

import json
from pathlib import Path

import pytest

from bgm import render, templates

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["acoustic", "comical", "drama_strings"]


def test_real_type_list_is_exactly_the_three_types():
    assert templates.list_styles() == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_bgm_new_with_real_template_loads_and_compiles(tmp_path, name):
    song_id = f"new_{name}"
    path = templates.new_song(song_id, name, songs_dir=tmp_path)
    assert Path(path) == tmp_path / song_id / "song.json"
    _, song = render.load_song(str(path))
    assert song["id"] == song_id and song["style"] == name
    result = render.compile_song(song)
    assert result["notes"]["melody"] == []
    for part in song["parts"][1:]:
        assert result["notes"].get(part["name"]) or result["rhythm"].get(part["name"]), part["name"]


@pytest.mark.parametrize("name", NAMES)
def test_sample_song_equals_bgm_new_output_except_melody(tmp_path, name):
    song_id = f"phase1_{name}"
    generated = json.loads(Path(templates.new_song(song_id, name, songs_dir=tmp_path)).read_text(encoding="utf-8"))
    sample = json.loads((ROOT / "songs" / song_id / "song.json").read_text(encoding="utf-8"))
    sample.pop("title", None)
    sample.pop("usage", None)
    assert list(sample) == list(generated)
    for got, want in zip(sample["parts"], generated["parts"], strict=True):
        if got["name"] == "melody":
            want = {k: v for k, v in want.items() if k != "note"}
            assert got["phrases"] != want["phrases"]
            got, want = dict(got, phrases=None), dict(want, phrases=None)
        assert got == want
    assert {k: v for k, v in sample.items() if k != "parts"} == {k: v for k, v in generated.items() if k != "parts"}
