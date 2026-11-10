"""全合成音色の曲全体レンダーの決定性を検証する。"""

import copy
import json
import subprocess
import sys

import numpy as np
import soundfile as sf

from bgm import render, synth
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


def assert_snapshot_equal(first, second):
    assert first.keys() == second.keys()
    for name in first:
        np.testing.assert_array_equal(first[name], second[name], err_msg=name)


def test_interleaved_calls_partial_cache_and_separate_process(tmp_path):
    design = synth_song()
    (tmp_path / "song.json").write_text(json.dumps(design), encoding="utf-8")
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    first = snapshot(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    changed = copy.deepcopy(design)
    changed["id"] = "other"
    changed["parts"].reverse()
    (other / "song.json").write_text(json.dumps(changed), encoding="utf-8")
    render.render_song(str(other), force=True, mp3=False, log=lambda *_: None)
    for name, audio in first.items():
        if name.startswith("stems"):
            np.testing.assert_array_equal(audio, sf.read(other / name, dtype="float32", always_2d=True)[0])
    for kind in SYNTH_PITCHED:
        synth.render_pitched(kind, 67, 100, 0.2)
    for kind in SYNTH_DRUMS:
        synth.render_drum(kind, 100)
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    assert_snapshot_equal(first, snapshot(tmp_path))
    for i, kind in enumerate([*SYNTH_PITCHED, *SYNTH_DRUMS]):
        if i % 2:
            (tmp_path / "stems" / f"{kind}.wav").unlink()
    render.render_song(str(tmp_path), mp3=False, log=lambda *_: None)
    assert_snapshot_equal(first, snapshot(tmp_path))
    result = subprocess.run([
        sys.executable, "-c",
        "from bgm.render import render_song; import sys; "
        "render_song(sys.argv[1], force=True, mp3=False, log=lambda *_: None)",
        str(tmp_path),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert_snapshot_equal(first, snapshot(tmp_path))
    for part in design["parts"]:
        part.update(volume=0.3, pan=0.7, mute=True, solo=True, note="注釈")
    (tmp_path / "song.json").write_text(json.dumps(design), encoding="utf-8")
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    second = snapshot(tmp_path)
    assert_snapshot_equal({k: v for k, v in first.items() if k.startswith("stems")},
                          {k: v for k, v in second.items() if k.startswith("stems")})


def test_all_direct_voices_ignore_call_history():
    for kind in SYNTH_PITCHED:
        first = synth.render_pitched(kind, 60, 90, 0.1)
        synth.render_pitched("bass", 67, 100, 0.2)
        np.testing.assert_array_equal(first, synth.render_pitched(kind, 60, 90, 0.1))
    for kind in SYNTH_DRUMS:
        first = synth.render_drum(kind, 90)
        synth.render_drum("noise_hit", 100)
        np.testing.assert_array_equal(first, synth.render_drum(kind, 90))


def test_random_primitives_use_local_seed():
    for fn, args in [(synth.karplus, (220, 1000)), (synth.bandpass_noise, (1000, 1000, 5000))]:
        first = fn(*args)
        fn(*args, seed=91)
        np.testing.assert_array_equal(first, fn(*args))
        assert not np.array_equal(first, fn(*args, seed=92))


def test_humanized_reverberant_song_remains_deterministic(tmp_path):
    design = synth_song()
    design["master"]["reverb"] = "room"
    design["swing"] = 0.3
    for part in design["parts"]:
        part.pop("humanize")
    (tmp_path / "song.json").write_text(json.dumps(design), encoding="utf-8")
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    first = snapshot(tmp_path)
    render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
    assert_snapshot_equal(first, snapshot(tmp_path))


def test_seed_identity_numeric_normalization_and_simultaneous_voices():
    seed = render._synth_seed
    assert seed("p", "bass", 0, 0, 0, 60) == seed("p", "bass", -0.0, 0, 0, 60)
    assert seed("p", "bass", 1, 0, 0, 60) == seed("p", "bass", 1.0, 0, 0, 60)
    identities = [("p", "bass", 0, 0, 0, 60), ("p", "bass", 0, 0, 1, 64),
                  ("p", "bass", 0, 1, 0, 60), ("p", "noise_hit", 0, 0), ("p", "hat", 0, 0)]
    assert len({seed(*identity) for identity in identities}) == len(identities)


def test_duplicate_ordinals_are_local_to_event_identity(monkeypatch):
    song = {"tempo": 120, "bars": 2, "beats_per_bar": 4, "loop": True,
            "swing": 0, "master": {"reverb": "none"}}
    part = {"name": "p", "instrument": "bass", "humanize": 0}
    events = [(0, [60, 64], 1, 90), (0, [60, 64], 1, 90)]
    monkeypatch.setattr(render, "parse_note_bars", lambda *_: events)
    seeds = []
    monkeypatch.setattr(synth, "render_pitched", lambda *args, seed: seeds.append(seed) or np.zeros((1, 2), np.float32))
    render.render_part(part, song)
    before = seeds.copy()
    seeds.clear()
    events.insert(1, (0.5, [67], 0.5, 80))
    render.render_part(part, song)
    assert seeds[:2] + seeds[3:] == before
    assert len(set(before)) == 4


def test_engine_version_invalidates_old_cache(tmp_path, monkeypatch):
    (tmp_path / "song.json").write_text(json.dumps(synth_song()), encoding="utf-8")
    _, song = render.load_song(str(tmp_path))
    current = [render.part_hash(part, song) for part in song["parts"]]
    monkeypatch.setattr(render, "ENGINE_VERSION", "0.1")
    assert all(render.part_hash(part, song) != h for part, h in zip(song["parts"], current, strict=True))
