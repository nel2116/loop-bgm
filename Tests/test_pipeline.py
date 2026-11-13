"""書き出しの段階分け（#75）: out/ の配置、report.json と build/notes.json の形、音が変わらないこと。

形式の契約は docs/design/phase2-pipeline.md の 2-4 節。
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from bgm import render
from bgm.checks import registered
from bgm.paths import SR

ROOT = Path(__file__).resolve().parent.parent

SONG = {
    "id": "pipe",
    "usage": "game",
    "tempo": 120,
    "bars": 2,
    "loop": True,
    "parts": [
        {"name": "lead", "role": "melody", "instrument": "square", "humanize": 0, "bars": ["C4:1 E4:1 G4:1 C5:1", "G4:2 E4:2"]},
        {"name": "low", "instrument": "bass", "humanize": 0, "volume": 0.5, "pan": -0.3, "bars": ["C3:4", "G2:4"]},
        {"name": "beat", "type": "drums", "humanize": 0, "bars": [{"kick": "x...x...", "hat": "..x...x."}]},
    ],
}

ISSUE_KEYS = ["level", "check", "part", "bars", "message", "hint"]
EVENT_KEYS = ["bar", "beat", "time", "seconds", "midi", "drum", "duration", "velocity", "instrument"]


def write_song(folder, song=SONG):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "song.json").write_text(json.dumps(song, ensure_ascii=False), encoding="utf-8")
    return folder


def render_quiet(folder, **kwargs):
    log = []
    path = render.render_song(str(folder), mp3=False, log=log.append, **kwargs)
    return path, log


def old_mix(song, folder):
    """#75 より前の render_song の mix 部分の写し。stems/ に書かれたパートの音から混ぜ直す。"""
    stems = {p["name"]: sf.read(folder / "stems" / f"{p['name']}.wav", dtype="float32", always_2d=True)[0] for p in song["parts"]}
    n = max(len(a) for a in stems.values())
    mix = np.zeros((n, 2), np.float32)
    solo = [p for p in song["parts"] if p.get("solo")]
    for part in song["parts"]:
        if part.get("mute") or (solo and not part.get("solo")):
            continue
        a = stems[part["name"]]
        gl, gr = render.pan_gains(part.get("pan", 0))
        mix[:len(a)] += a * (np.array([gl, gr], np.float32) * np.float32(part.get("volume", 0.8)))
    peak = np.abs(mix).max()
    target = 10 ** (-1 / 20) * 10 ** (min(0, song["master"]["gain_db"]) / 20)
    gain = target / peak if peak > 0 else 1.0
    mix *= np.float32(gain)
    if not song["loop"]:
        fade = min(len(mix), int(0.05 * SR))
        mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return mix


def assert_report_schema(doc, song_id):
    assert list(doc) == ["song", "version", "passed", "metrics", "issues"]
    assert doc["song"] == song_id and doc["version"] == 1 and isinstance(doc["passed"], bool)
    assert list(doc["metrics"])[:3] == ["lufs", "peak_db", "loop_seconds"]
    for issue in doc["issues"]:
        assert list(issue) == ISSUE_KEYS
        assert issue["level"] in ("error", "warning") and issue["check"] in registered()
        assert issue["bars"] == sorted(set(issue["bars"]))
    assert doc["passed"] == (not any(i["level"] == "error" for i in doc["issues"]))


def assert_notes_schema(doc, song):
    assert list(doc) == ["song", "version", "tempo", "beats_per_bar", "bars", "seconds", "loop", "parts"]
    assert doc["song"] == song["id"] and doc["version"] == 1 and doc["loop"] == song["loop"]
    assert [p["name"] for p in doc["parts"]] == [p["name"] for p in song["parts"]]
    for part in doc["parts"]:
        assert list(part) == ["name", "role", "type", "instrument", "events"]
        assert part["type"] in ("notes", "drums")
        for event in part["events"]:
            assert list(event) == EVENT_KEYS
            assert 1 <= event["bar"] <= doc["bars"]
            assert 0 <= event["beat"] < doc["beats_per_bar"]
            if part["type"] == "drums":
                assert event["midi"] is None and event["duration"] is None and event["drum"] == event["instrument"]
            else:
                assert isinstance(event["midi"], int) and event["drum"] is None and event["duration"] > 0
            assert 1 <= event["velocity"] <= 127


def test_render_writes_out_report_and_notes(tmp_path):
    folder = write_song(tmp_path / "pipe")
    path, log = render_quiet(folder)
    assert path == folder / "out" / "pipe.wav"
    assert not (folder / "pipe.wav").exists() and not (folder / "mix.json").exists()
    assert json.loads((folder / "build" / "mix.json").read_text(encoding="utf-8"))["seconds"] == pytest.approx(4.0)
    assert (folder / "last_song.json").exists()
    assert any(line.startswith("書き出し: ") for line in log)
    assert any("つなぎ目 OK" in line for line in log)

    report = json.loads((folder / "out" / "report.json").read_text(encoding="utf-8"))
    assert_report_schema(report, "pipe")
    assert report["metrics"]["loop_seconds"] == 4.0
    assert report["metrics"]["peak_db"] == pytest.approx(-1.0, abs=0.1)
    assert -40 < report["metrics"]["lufs"] < 0

    _, song = render.load_song(str(folder))
    notes = json.loads((folder / "build" / "notes.json").read_text(encoding="utf-8"))
    assert_notes_schema(notes, song)
    lead, low, beat = notes["parts"]
    assert (lead["role"], lead["instrument"], beat["instrument"]) == ("melody", "square", None)
    assert [e["midi"] for e in lead["events"]] == [60, 64, 67, 72, 67, 64]
    assert [(e["bar"], e["beat"], e["seconds"]) for e in lead["events"][4:]] == [(2, 0.0, 2.0), (2, 2.0, 3.0)]
    assert [e["duration"] for e in low["events"]] == [4.0, 4.0]
    assert {e["drum"] for e in beat["events"]} == {"kick", "hat"}


def test_report_and_notes_are_identical_across_renders(tmp_path):
    folder = write_song(tmp_path / "pipe")
    render_quiet(folder)
    first = [(folder / p).read_bytes() for p in ("out/report.json", "build/notes.json")]
    render_quiet(folder, force=True)
    assert [(folder / p).read_bytes() for p in ("out/report.json", "build/notes.json")] == first
    assert b"\r\n" not in first[0] and b"\r\n" not in first[1]


def test_old_layout_is_rotated_into_history_and_removed(tmp_path):
    folder = write_song(tmp_path / "pipe")
    sf.write(folder / "pipe.wav", np.zeros((SR, 2), np.float32), SR, subtype="PCM_16")
    (folder / "pipe.mp3").write_bytes(b"old")
    (folder / "mix.json").write_text("{}", encoding="utf-8")
    _, log = render_quiet(folder)
    assert not any((folder / name).exists() for name in ("pipe.wav", "pipe.mp3", "mix.json"))
    assert len(list((folder / "history").glob("*.wav"))) == 1
    assert any("古い場所の書き出しを片付けました" in line for line in log)
    render_quiet(folder, force=True)
    assert len(list((folder / "history").glob("*.wav"))) >= 1


def test_master_equals_old_mix_code(tmp_path):
    folder = write_song(tmp_path / "pipe")
    path, _ = render_quiet(folder)
    _, song = render.load_song(str(folder))
    expected = tmp_path / "expected.wav"
    sf.write(expected, old_mix(song, folder), SR, subtype="PCM_16")
    assert np.array_equal(sf.read(path, dtype="int16")[0], sf.read(expected, dtype="int16")[0])


def _needs_samples(song_id):
    """曲が録音音源を使うか。読み込めない曲は音源なしとみなし、テストのほうで失敗させる。"""
    from bgm import sampler

    try:
        _, song = render.load_song(song_id)
    except render.SongError:
        return False
    original = sampler.missing_samples
    sampler.missing_samples = lambda instruments, drums: sorted(instruments) + sorted(drums)
    try:
        render.check_samples(song)
    except render.SongError:
        return True
    finally:
        sampler.missing_samples = original
    return False


def _example_songs():
    for folder in sorted(p.parent for p in (ROOT / "songs").glob("*/song.json")):
        marks = [pytest.mark.slow] + ([pytest.mark.samples] if _needs_samples(folder.name) else [])
        yield pytest.param(folder.name, marks=marks)


@pytest.mark.parametrize("song_id", list(_example_songs()))
def test_example_song_master_equals_old_mix_code(tmp_path, song_id):
    """songs/ の曲ごとに、新しい out/<id>.wav が #75 より前の mix の結果と同じサンプルになる。"""
    folder = tmp_path / song_id
    shutil.copytree(ROOT / "songs" / song_id, folder,
                    ignore=shutil.ignore_patterns("stems", "out", "build", "history", "*.wav", "*.mp3"))
    path, _ = render_quiet(folder)
    _, song = render.load_song(str(folder))
    expected = tmp_path / "expected.wav"
    sf.write(expected, old_mix(song, folder), SR, subtype="PCM_16")
    assert np.array_equal(sf.read(path, dtype="int16")[0], sf.read(expected, dtype="int16")[0])
