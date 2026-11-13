"""bgm/templates.py と `bgm new` の単体テスト（tmp_path の一時テンプレートだけを使う）。"""

import copy
import json

import pytest

from bgm import templates
from bgm.__main__ import main
from bgm.render import compile_song, load_song, part_hash

RESTS = " | ".join([". . . . . . . ."] * 8)

SONG = {
    "tempo": 96, "key": "C major", "meter": "4/4", "form": ["A", "A'", "B", "A"],
    "sections": {"A": {"bars": 8, "chords": "I | vi | IV | V | I | vi | ii V | I"},
                 "B": {"bars": 8, "chords": "IV | V | iii | vi | IV | V | I | V"}},
    "master": {"reverb": "room"},
    "parts": [
        {"name": "melody", "role": "melody", "instrument": "kalimba", "grid": "1/8",
         "phrases": {"A": RESTS, "B": RESTS}, "note": "仮のメロディ（休符のみ）。度数で書き換える", "volume": 0.5},
        {"name": "guitar", "role": "chords", "instrument": "nylon_guitar", "style": "strum", "volume": 0.4},
        {"name": "bass", "role": "bass", "instrument": "bass", "style": "root_fifth", "volume": 0.4},
        {"name": "drums", "role": "rhythm", "groove": "bongo_8beat", "kit": ["bongo_hi", "bongo_lo", "tambourine"], "volume": 0.35}],
    "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                  {"section": "B", "part": "guitar", "do": "instrument", "instrument": "e_piano"}],
}


def template(name="demo", **changes):
    data = {"name": name, "ja": "テスト用", "tempo_range": [80, 110], "song": copy.deepcopy(SONG)}
    data.update(changes)
    return data


def write_template(folder, stem, data):
    folder.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    (folder / f"{stem}.json").write_text(text, encoding="utf-8")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    tdir, sdir = tmp_path / "templates", tmp_path / "songs"
    sdir.mkdir()
    write_template(tdir, "demo", template())
    monkeypatch.setattr(templates, "TEMPLATES", tdir)
    monkeypatch.setattr(templates, "SONGS", sdir)
    return tdir, sdir


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def snapshot(folder):
    return sorted((str(p.relative_to(folder)), p.read_bytes() if p.is_file() else None) for p in folder.rglob("*"))


# ---------------------------------------------------------------- type list and validation

def test_list_styles_is_sorted_stems(tmp_path):
    for stem in ("zeta", "acoustic", "mid_one"):
        write_template(tmp_path, stem, template(stem))
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    assert templates.list_styles(tmp_path) == ["acoustic", "mid_one", "zeta"]
    assert templates.list_styles(tmp_path / "missing") == []


def test_valid_template_loads(tmp_path):
    write_template(tmp_path, "demo", template())
    assert templates.load_template("demo", tmp_path)["ja"] == "テスト用"


def _song_with(**changes):
    song = copy.deepcopy(SONG)
    song.update(changes)
    return song


BROKEN = {
    "unknown_key": (template(extra=1), "知らないキー"),
    "missing_key": ({k: v for k, v in template().items() if k != "ja"}, "ja がありません"),
    "name_not_stem": (template("other"), "name はファイル名"),
    "ja_empty": (template(ja=""), "ja は空でない"),
    "ja_not_string": (template(ja=3), "ja は空でない"),
    "tempo_range_short": (template(tempo_range=[80]), "tempo_range は整数2つ"),
    "tempo_range_float": (template(tempo_range=[80, 110.5]), "tempo_range は整数2つ"),
    "tempo_range_bool": (template(tempo_range=[True, 110]), "tempo_range は整数2つ"),
    "tempo_range_reversed": (template(tempo_range=[110, 80]), "最大 80 より大きく"),
    "song_not_object": (template(song=[]), "song はオブジェクト"),
    "tempo_outside": (template(song=_song_with(tempo=120)), "tempo_range 80–110 の外"),
    "tempo_not_number": (template(song=_song_with(tempo="96")), "song.tempo は数値"),
    "tempo_bool": (template(song=_song_with(tempo=True)), "song.tempo は数値"),
    "not_object": ([1, 2], "オブジェクトにしてください"),
    "invalid_json": ('{"name": "demo",', "JSON の書式エラー"),
    **{f"song_has_{k}": (template(song=_song_with(**{k: "x"})), f"song に {k} を書かないで")
       for k in ("id", "style", "title", "usage")},
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_template_is_refused(roots, capsys, case):
    tdir, sdir = roots
    data, reason = BROKEN[case]
    write_template(tdir, "demo", data)
    code, out, err = run(capsys, "new", "x", "--style", "demo")
    assert code == 1 and out == ""
    assert err.startswith("曲の型 demo のファイルが壊れています: ")
    assert reason in err
    assert err.count("\n") == 1
    assert list(sdir.iterdir()) == []


def test_template_song_rejected_by_load_song_is_broken(roots, capsys):
    tdir, sdir = roots
    data = template()
    data["song"]["parts"][1]["style"] = "no_such_style"
    write_template(tdir, "demo", data)
    code, _, err = run(capsys, "new", "x", "--style", "demo")
    assert code == 1
    assert err.startswith("曲の型 demo のファイルが壊れています: 雛形が設計図として読めません: ")
    assert list(sdir.iterdir()) == []


# ---------------------------------------------------------------- bgm new success

def test_new_writes_song(roots, capsys):
    tdir, sdir = roots
    code, out, err = run(capsys, "new", "my_song_1", "--style", "demo")
    assert (code, err) == (0, "")
    assert out == "作成しました: songs/my_song_1/song.json（型: demo）\n"
    path = sdir / "my_song_1" / "song.json"
    assert [p.name for p in sdir.iterdir()] == ["my_song_1"]
    assert [p.name for p in path.parent.iterdir()] == ["song.json"]
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw and raw.endswith(b"}\n")
    expected = {"id": "my_song_1", "style": "demo", **SONG}
    assert raw.decode("utf-8") == json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    written = json.loads(raw)
    assert list(written) == ["id", "style", *SONG]
    assert written == expected

    _, song = load_song(str(path))
    compiled = compile_song(song)
    assert set(compiled["notes"]) | set(compiled["rhythm"]) == {"melody", "guitar", "bass", "drums"}
    assert compiled["notes"]["melody"] == []
    assert compiled["notes"]["guitar"] and compiled["notes"]["bass"] and compiled["rhythm"]["drums"]


def test_new_is_deterministic(tmp_path):
    tdir = tmp_path / "templates"
    write_template(tdir, "demo", template())
    a = templates.new_song("same", "demo", templates_dir=tdir, songs_dir=tmp_path / "a")
    b = templates.new_song("same", "demo", templates_dir=tdir, songs_dir=tmp_path / "b")
    assert a != b and a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------- refusals

@pytest.mark.parametrize("song_id", ["Upper", "has-dash", "sp ace", "", "../up", "日本語"])
def test_bad_song_id(roots, capsys, song_id):
    _, sdir = roots
    code, out, err = run(capsys, "new", song_id, "--style", "demo")
    assert (code, out) == (1, "")
    assert err == f"曲IDは英小文字・数字・_ だけで書いてください: {song_id}\n"
    assert list(sdir.iterdir()) == []


@pytest.mark.parametrize("kind", ["song", "empty_folder", "file"])
def test_existing_song_is_not_overwritten(roots, capsys, kind):
    _, sdir = roots
    if kind == "song":
        assert run(capsys, "new", "x", "--style", "demo")[0] == 0
    elif kind == "empty_folder":
        (sdir / "x").mkdir()
    else:
        (sdir / "x").write_text("keep", encoding="utf-8")
    before = snapshot(sdir)
    code, out, err = run(capsys, "new", "x", "--style", "demo")
    assert (code, out) == (1, "")
    assert err == "曲フォルダ songs/x はすでにあります。別の曲IDにしてください\n"
    assert snapshot(sdir) == before


def test_existing_check_comes_before_unknown_style(roots, capsys):
    _, sdir = roots
    (sdir / "x").mkdir()
    _, _, err = run(capsys, "new", "x", "--style", "nope")
    assert err.startswith("曲フォルダ songs/x はすでにあります")


@pytest.mark.parametrize("style", ["nope", "../demo", "DEMO", "demo.json", ""])
def test_unknown_style(roots, capsys, style):
    tdir, sdir = roots
    write_template(tdir, "another", template("another"))
    code, out, err = run(capsys, "new", "x", "--style", style)
    assert (code, out) == (1, "")
    assert err == f"曲の型 {style} はありません（使える型: another / demo）\n"
    assert list(sdir.iterdir()) == []


def test_missing_style_option_is_usage_error(roots):
    with pytest.raises(SystemExit) as e:
        main(["new", "x"])
    assert e.value.code == 2


# ---------------------------------------------------------------- song-level style is not read

def test_song_level_style_is_ignored(tmp_path):
    tdir = tmp_path / "templates"
    write_template(tdir, "demo", template())
    path = templates.new_song("x", "demo", templates_dir=tdir, songs_dir=tmp_path / "songs")
    _, with_style = load_song(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["style"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _, without_style = load_song(str(path))
    assert compile_song(with_style) == compile_song(without_style)
    for a, b in zip(with_style["parts"], without_style["parts"], strict=True):
        assert part_hash(a, with_style) == part_hash(b, without_style)
