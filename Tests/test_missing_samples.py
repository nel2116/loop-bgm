"""音源のない楽器を使う曲の書き出しが、日本語の 1 行で止まり stems/ を残さないことの検証 (#70)。"""

import json
from pathlib import Path

import pytest

from bgm import __main__ as cli
from bgm import render, sampler

VARIATIONS = Path(__file__).resolve().parents[1] / "songs/phase1_variations/song.json"


@pytest.fixture
def no_samples(tmp_path, monkeypatch):
    """音源フォルダを空のフォルダに向け、読み込み済みの楽器も忘れさせる。"""
    empty = tmp_path / "samples"
    empty.mkdir()
    monkeypatch.setattr(sampler, "VSCO", empty)
    monkeypatch.setattr(render, "_inst_cache", {})
    return empty


def write_song(folder, song):
    folder.mkdir()
    (folder / "song.json").write_text(json.dumps(song, ensure_ascii=False), encoding="utf-8")
    return folder


def legacy_song():
    return {
        "tempo": 120, "bars": 2, "master": {"reverb": "room"},
        "parts": [
            {"name": "melody", "instrument": "flute", "bars": ["C5:2 E5:2"]},
            {"name": "drums", "type": "drums", "bars": [{"orch_bd": "x...", "kick": "..x."}]},
            {"name": "pad", "instrument": "e_piano", "bars": ["C4:4"]},
        ],
    }


def test_render_names_all_missing_samples_in_one_line(no_samples, tmp_path, capsys):
    folder = write_song(tmp_path / "song", legacy_song())

    code = cli.main(["render", str(folder), "--no-mp3"])

    err = capsys.readouterr().err
    assert code == 1
    assert err.count("\n") == 1 and err.startswith("エラー:")
    assert "Traceback" not in err
    assert "flute" in err and "orch_bd" in err
    assert "bgm fetch flute orch_bd" in err
    assert "e_piano" not in err and "kick" not in err  # 合成の楽器は名指ししない。
    assert not (folder / "stems").exists()


def test_variation_instrument_switch_is_checked(no_samples):
    song = json.loads(VARIATIONS.read_text(encoding="utf-8"))
    for rule in song["variation"]:
        if rule.get("do") == "instrument" and rule["part"] == "melody":
            rule["instrument"] = "flute"

    with pytest.raises(render.SongError) as exc:
        render.check_samples(song)

    assert "flute" in str(exc.value)


def test_synth_only_song_passes_without_samples(no_samples):
    song = json.loads(VARIATIONS.read_text(encoding="utf-8"))

    render.check_samples(song)


def test_render_reports_os_error_in_one_line(monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise OSError("書き込めません")

    monkeypatch.setattr(render, "render_song", broken)

    code = cli.main(["render", "whatever", "--no-mp3"])

    err = capsys.readouterr().err
    assert code == 1
    assert err == "エラー: 書き込めません\n"
