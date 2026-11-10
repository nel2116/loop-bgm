"""全合成音色の曲全体レンダーの決定性を検証する。"""

import json

import numpy as np
import soundfile as sf

from bgm import render
from bgm.instruments import SYNTH_DRUMS, SYNTH_PITCHED


def synth_song():
    return {
        "id": "all_synth",
        "tempo": 180,
        "bars": 2,
        "master": {"reverb": "none"},
        "parts": [
            {"name": kind, "instrument": kind, "bars": ["C3+E3:1 G3:1 C4:2"], "humanize": 0}
            for kind in SYNTH_PITCHED
        ] + [
            {"name": kind, "type": "drums", "bars": [{kind: "x.x."}], "humanize": 0}
            for kind in SYNTH_DRUMS
        ],
    }


def snapshot(folder):
    paths = [folder / "all_synth.wav", *sorted((folder / "stems").glob("*.wav"))]
    return {str(path.relative_to(folder)): sf.read(path, dtype="float32", always_2d=True)[0] for path in paths}


def test_consecutive_forced_full_song_renders(tmp_path):
    (tmp_path / "song.json").write_text(json.dumps(synth_song()), encoding="utf-8")
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    first = snapshot(tmp_path)
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    second = snapshot(tmp_path)
    mismatches = {
        name: int(np.count_nonzero(audio != second[name]))
        for name, audio in first.items() if not np.array_equal(audio, second[name])
    }
    assert not mismatches, mismatches
