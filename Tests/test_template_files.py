"""templates/*.json と見本曲が設計記録 docs/design/phase1-templates.md のとおりかを確かめる。

テンプレートの検証関数は bgm/templates.py（別ワーカー担当）にあるため、ここでは記録の規則を
JSON を直接読んで確かめる。音源は使わない（load_song / compile_song とファイルの検査だけ）。
"""

import json
import re
from pathlib import Path

import pytest

from bgm import chords, instruments, render, rhythm

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
NAMES = ["acoustic", "comical", "drama_strings"]
REST_BARS = " | ".join([". . . . . . . ."] * 8)
NOTE = "仮のメロディ（休符のみ）。度数で書き換える"
BASS_STYLES = ("root_whole", "root_quarter", "root_fifth", "octave_8th", "walking", "arpeggio")
FORM = ["A", "A'", "B", "A"]

# 設計記録「The first three templates」の表
EXPECTED = {
    "acoustic": {
        "ja": "アコースティック小編成", "tempo_range": [80, 110], "tempo": 96, "key": "C major",
        "parts": [("melody", "melody", "flute", None), ("guitar", "chords", "nylon_guitar", "strum"),
                  ("bass", "bass", "piano", "root_fifth")],
        "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                      {"section": "B", "part": "guitar", "do": "instrument", "instrument": "piano"}],
    },
    "comical": {
        "ja": "コミカル", "tempo_range": [120, 160], "tempo": 144, "key": "C major",
        "parts": [("melody", "melody", "xylophone", None), ("chords", "chords", "violins_pizz", "offbeat"),
                  ("bass", "bass", "bassoon_stac", "root_fifth"), ("drums", "rhythm", None, "bongo_8beat")],
        "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                      {"part": "drums", "do": "fill_last_bar", "every": 8}],
    },
    "drama_strings": {
        "ja": "ドラマチックな弦", "tempo_range": [70, 140], "tempo": 112, "key": "A minor",
        "parts": [("melody", "melody", "violins", None), ("arp", "chords", "violas", "arpeggio_up"),
                  ("horn", "chords", "horn", "pad"), ("bass", "bass", "cellos", "root_quarter"),
                  ("timpani", None, None, None)],
        "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                      {"part": "arp", "do": "period", "beats": 3}],
    },
}


def load_template(name):
    raw = (TEMPLATES / f"{name}.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    return json.loads(raw.decode("utf-8"))


def load_sample(name):
    return json.loads((ROOT / "songs" / f"phase1_{name}" / "song.json").read_text(encoding="utf-8"))


def write_song(tmp_path, song_id, design):
    folder = tmp_path / song_id
    folder.mkdir()
    (folder / "song.json").write_text(json.dumps(design, ensure_ascii=False), encoding="utf-8")
    return str(folder)


def test_template_folder_has_exactly_the_three_types():
    assert sorted(p.stem for p in TEMPLATES.glob("*.json")) == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_template_format(name):
    template = load_template(name)
    assert list(template) == ["name", "ja", "tempo_range", "song"]
    assert template["name"] == name
    assert isinstance(template["ja"], str) and template["ja"]
    low, high = template["tempo_range"]
    assert type(low) is int and type(high) is int and low <= high
    song = template["song"]
    assert isinstance(song, dict)
    assert not {"id", "style", "title", "usage", "scene"} & set(song)
    assert type(song["tempo"]) in (int, float) and low <= song["tempo"] <= high


@pytest.mark.parametrize("name", NAMES)
def test_template_matches_record_table(name):
    template, expected = load_template(name), EXPECTED[name]
    song = template["song"]
    assert template["ja"] == expected["ja"]
    assert template["tempo_range"] == expected["tempo_range"]
    assert song["tempo"] == expected["tempo"]
    assert song["key"] == expected["key"]
    assert song["meter"] == "4/4"
    assert song["form"] == FORM
    assert {k: v["bars"] for k, v in song["sections"].items()} == {"A": 8, "B": 8}
    assert song["master"] == {"reverb": "room"}
    parts = [(p["name"], p.get("role"), p.get("instrument"), p.get("style") or p.get("groove")) for p in song["parts"]]
    assert parts == expected["parts"]
    assert song["variation"] == expected["variation"]


def test_template_specific_rhythm_parts():
    comical = {p["name"]: p for p in load_template("comical")["song"]["parts"]}
    assert comical["drums"]["kit"] == ["bongo_hi", "bongo_lo", "tambourine"]
    drama = {p["name"]: p for p in load_template("drama_strings")["song"]["parts"]}
    assert drama["timpani"]["type"] == "drums"
    assert drama["timpani"]["bars"] == [{"timpani": "x.......x......."}]
    assert all(p.get("role") != "rhythm" for p in load_template("acoustic")["song"]["parts"])


@pytest.mark.parametrize("name", NAMES)
def test_instruments_exist_in_catalog(name):
    song = load_template(name)["song"]
    pitched = set(instruments.SAMPLED) | set(instruments.SYNTH_PITCHED)
    drums = set(instruments.PERCUSSION) | set(instruments.SYNTH_DRUMS)
    for part in song["parts"]:
        if "instrument" in part:
            assert part["instrument"] in pitched, part["name"]
        for voice in part.get("kit", []):
            assert voice in drums, part["name"]
        for bar in part.get("bars", []):
            if isinstance(bar, dict):
                assert set(bar) <= drums, part["name"]
    for rule in song["variation"]:
        if rule["do"] == "instrument":
            assert rule["instrument"] in pitched


def test_template_names_differ_from_accompaniment_styles_and_grooves():
    grooves = {groove for groove, _meter in rhythm._PATTERNS} | {"ambient_none"}
    reserved = set(chords._STYLES) | set(BASS_STYLES) | grooves
    assert not set(NAMES) & reserved


@pytest.mark.parametrize("name", NAMES)
def test_melody_placeholder_is_rests_only(name):
    melody = load_template(name)["song"]["parts"][0]
    assert melody["name"] == "melody" and melody["grid"] == "1/8"
    assert melody["note"] == NOTE
    assert melody["phrases"] == {"A": REST_BARS, "B": REST_BARS}
    for phrase in melody["phrases"].values():
        assert re.fullmatch(r"[.| ]+", phrase)


@pytest.mark.parametrize("name", NAMES)
def test_template_skeleton_loads_and_compiles(tmp_path, name):
    design = {"id": f"new_{name}", "style": name, "usage": "video", **load_template(name)["song"]}
    _, song = render.load_song(write_song(tmp_path, f"new_{name}", design))
    result = render.compile_song(song)
    assert result["notes"]["melody"] == []
    for part in song["parts"][1:]:
        assert result["notes"].get(part["name"]) or result["rhythm"].get(part["name"]), part["name"]


@pytest.mark.parametrize("name", NAMES)
def test_sample_song_loads_and_compiles_every_part(name):
    _, song = render.load_song(f"phase1_{name}")
    result = render.compile_song(song)
    for part in song["parts"]:
        assert result["notes"].get(part["name"]) or result["rhythm"].get(part["name"]), part["name"]


@pytest.mark.parametrize("name", NAMES)
def test_sample_song_differs_from_template_only_in_melody(name):
    template, sample = load_template(name)["song"], load_sample(name)
    assert sample["id"] == f"phase1_{name}"
    assert sample["style"] == name
    assert set(sample) - {"title", "usage", "scene"} == {"id", "style", *template}
    for key, value in template.items():
        if key != "parts":
            assert sample[key] == value, key
    assert [p["name"] for p in sample["parts"]] == [p["name"] for p in template["parts"]]
    for got, want in zip(sample["parts"], template["parts"], strict=True):
        if got["name"] == "melody":
            assert "note" not in got
            assert got["phrases"] != want["phrases"]
            assert {k: v for k, v in got.items() if k != "phrases"} == {
                k: v for k, v in want.items() if k not in ("phrases", "note")}
        else:
            assert got == want
