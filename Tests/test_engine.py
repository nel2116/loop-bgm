# 書き出しエンジン(bgm/)の回帰テスト。音源のダウンロードは要らない(合成音だけを使う)。
#
#   python -m pytest -q Tests/test_engine.py
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from bgm.paths import SR
from bgm.render import SongError, check_loop, fold_loop, load_song, parse_note_bars, render_song, song_seconds
from bgm.theory import midi_to_name, note_to_midi, parse_pitches

SYNTH_SONG = {
    "title": "合成音だけの見本",
    "tempo": 120,
    "bars": 4,
    "master": {"reverb": "room"},
    "parts": [
        {"name": "drums", "type": "drums", "bars": [{"kick": "x...x...", "snare": "..x...x.", "hat": "xxxxxxxx"}]},
        {"name": "bass", "instrument": "bass", "bars": ["C2:2 G2:2", "A1:2 E2:2", "F1:2 C2:2", "G1:2 D2:2"]},
        {"name": "pad", "instrument": "pad", "volume": 0.4, "bars": ["C4+E4+G4:4", "C4+E4+A4:4", "C4+F4+A4:4", "B3+D4+G4:4"]},
        {"name": "lead", "instrument": "square", "volume": 0.5,
         "bars": ["C5:1 E5:1 G5:1 E5:1", "A5:2 G5:2", "F5:1 E5:1 D5:1 C5:1", "D5:4"]},
    ],
}


@pytest.fixture
def song_dir(tmp_path):
    d = tmp_path / "synth_song"
    d.mkdir()
    (d / "song.json").write_text(json.dumps(SYNTH_SONG, ensure_ascii=False), encoding="utf-8")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- theory

def test_note_names_round_trip():
    assert note_to_midi("C4") == 60
    assert note_to_midi("A4") == 69
    assert note_to_midi("C#4") == note_to_midi("Db4") == 61
    assert midi_to_name(60) == "C4"


def test_chord_token_gives_all_pitches():
    assert parse_pitches("C4+E4+G4") == [60, 64, 67]


# ---------------------------------------------------------------- parsing

def test_parse_note_bars_cycles_segments_to_fill_the_song():
    song = {"beats_per_bar": 4, "bars": 4}
    events = parse_note_bars({"name": "p", "bars": ["C4:4"]}, song)
    assert [e[0] for e in events] == [0, 4, 8, 12]


def test_bar_with_wrong_length_is_an_error_in_japanese():
    song = {"beats_per_bar": 4, "bars": 1}
    with pytest.raises(SongError, match="拍"):
        parse_note_bars({"name": "p", "bars": ["C4:3"]}, song)


def test_unreadable_token_names_the_part_and_bar():
    song = {"beats_per_bar": 4, "bars": 1}
    with pytest.raises(SongError, match=r"\[melody\] 1番目の小節"):
        parse_note_bars({"name": "melody", "bars": ["C4-4"]}, song)


def test_missing_required_keys_is_an_error(tmp_path):
    (tmp_path / "song.json").write_text(json.dumps({"tempo": 100}), encoding="utf-8")
    with pytest.raises(SongError, match="bars"):
        load_song(str(tmp_path))


# ---------------------------------------------------------------- loop

def test_fold_loop_keeps_the_exact_length_and_wraps_the_tail():
    n = 100
    x = np.zeros((150, 2), np.float32)
    x[120] = 1.0  # rings 20 samples past the end
    out = fold_loop(x, n)
    assert out.shape == (n, 2)
    assert out[20, 0] == 1.0


def test_check_loop_flags_a_click_at_the_seam():
    t = np.arange(SR * 2) / SR
    smooth = np.stack([np.sin(2 * np.pi * 220 * t)] * 2, axis=1).astype(np.float32) * 0.3
    ok, _ = check_loop(smooth)
    assert ok
    clicked = smooth.copy()
    clicked[-1] = 0.9
    ok, msg = check_loop(clicked)
    assert not ok and "跳んで" in msg


# ---------------------------------------------------------------- render

@pytest.mark.slow
def test_render_synth_song_loops_without_a_seam(song_dir):
    out = render_song(str(song_dir), mp3=False, log=lambda *_: None)
    audio, sr = sf.read(out, always_2d=True)
    _, song = load_song(str(song_dir))
    assert sr == SR
    assert len(audio) == int(round(song_seconds(song) * SR))
    assert np.abs(audio).max() <= 10 ** (-1 / 20) + 1e-3
    ok, msg = check_loop(audio.astype(np.float32))
    assert ok, msg


@pytest.mark.slow
def test_second_render_reuses_unchanged_parts(song_dir):
    render_song(str(song_dir), mp3=False, log=lambda *_: None)
    song = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    song["parts"][1]["bars"] = ["C2:4", "A1:4", "F1:4", "G1:4"]
    (song_dir / "song.json").write_text(json.dumps(song, ensure_ascii=False), encoding="utf-8")
    lines = []
    render_song(str(song_dir), mp3=False, log=lines.append)
    rebuilt = [line.split()[0] for line in lines if "作り直し" in line]
    assert rebuilt == ["bass"]


def test_example_songs_parse():
    root = Path(__file__).resolve().parent.parent / "songs"
    for f in sorted(root.glob("*/song.json")):
        _, song = load_song(str(f))
        for part in song["parts"]:
            if part.get("type") != "drums":
                parse_note_bars(part, song)
