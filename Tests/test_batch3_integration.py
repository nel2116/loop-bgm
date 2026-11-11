"""追加型を共通load/compile/render/listen境界で検証する。"""

import copy
import json
import subprocess
import sys

import numpy as np
import pytest

from bgm import render, synth

BASS = ("octave_8th", "walking", "arpeggio")
CHORDS = ("arpeggio_up", "broken", "strum", "waltz")
GROOVES = ("16beat", "shuffle", "bossa", "swing_ride", "bongo_8beat")


def design(role="chords", pattern="strum", meter="4/4"):
    part = {"name": "generated", "role": role, "humanize": 0, "reverb": 0}
    if role == "rhythm":
        part.update(groove=pattern, kit=["kick", "snare", "hat", "rim", "ride", "bongo_hi", "bongo_lo", "tambourine"])
    else:
        part.update(style=pattern, instrument="nylon_guitar")
    return {"id": "batch3", "tempo": 120, "key": "C major", "meter": meter,
            "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": 1, "chords": "Iadd9/3 ii V"}, "B": {"bars": 1, "chords": "iv"}},
            "master": {"reverb": "none"}, "parts": [part]}


def load(tmp_path, song):
    (tmp_path / "song.json").write_text(json.dumps(song), encoding="utf-8")
    return render.load_song(str(tmp_path))[1]


@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
@pytest.mark.parametrize("role,pattern", [("bass", s) for s in BASS] + [("chords", s) for s in CHORDS]
                         + [("rhythm", s) for s in GROOVES])
def test_complete_new_meter_table(tmp_path, meter, role, pattern):
    song = design(role, pattern, meter)
    supported = (role != "rhythm" or meter == "4/4") and (pattern != "waltz" or meter == "3/4")
    if not supported:
        with pytest.raises(render.SongError, match=r"\[generated\].*小節"):
            load(tmp_path, song)
        return
    compiled = render.compile_song(load(tmp_path, song))
    events = compiled["rhythm" if role == "rhythm" else "notes"]["generated"]
    assert events
    assert all(0 <= event[0] < compiled["bars"] * compiled["beats_per_bar"] for event in events)


@pytest.mark.parametrize("pattern", CHORDS)
@pytest.mark.parametrize("octave,transpose", [(0, 0), (10, 2), (-10, -3)])
def test_new_chord_seed_uses_original_tone_but_delay_uses_tuple_index(tmp_path, monkeypatch, pattern, octave, transpose):
    song = design(pattern=pattern, meter="3/4")
    song["parts"][0].update(octave=octave, transpose=transpose, strum=.013)
    song = load(tmp_path, song)
    compiled = render.compile_song(song)
    calls, placements = [], []
    monkeypatch.setattr(render, "get_instrument", lambda *_: None)
    monkeypatch.setattr(synth, "render_pitched", lambda voice, midi, velocity, duration, *, seed:
                        calls.append((midi, seed)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: placements.append(start) or buf)
    render.render_part(song["parts"][0], song)
    expected, starts = [], []
    for beat, pitches, _, _ in compiled["notes"]["generated"]:
        chord = next(c for c in reversed(compiled["harmony"]) if c["beat"] <= beat)
        raw = [p + octave * 12 + transpose for p in chord["pitches"]]
        shift = min(max(0, -(min(raw) // 12)), (127 - max(raw)) // 12) * 12
        corrected = [p + shift for p in raw]
        for k, pitch in enumerate(pitches):
            expected.append((pitch, render._synth_seed("generated", "nylon_guitar", beat, 0, corrected.index(pitch), pitch)))
            starts.append(int((beat * .5 + k * .013) * render.SR))
    assert calls == expected
    assert placements == starts


@pytest.mark.parametrize("strum", [None, 0, -.02, .03])
def test_strum_default_only_when_absent_and_applied_once(tmp_path, monkeypatch, strum):
    song = design()
    song.update(form=["A"], sections={"A": {"bars": 1, "chords": "I"}})
    if strum is not None:
        song["parts"][0]["strum"] = strum
    song = load(tmp_path, song)
    placements = []
    monkeypatch.setattr(render, "get_instrument", lambda *_: None)
    monkeypatch.setattr(synth, "render_pitched", lambda *_, **__: np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: placements.append(start) or buf)
    render.render_part(song["parts"][0], song)
    delay = .02 if strum is None else strum
    assert placements == [int(max(0, beat * .5 + k * delay) * render.SR) for beat in range(4) for k in range(3)]


@pytest.mark.parametrize("groove,swing", [("shuffle", 0), ("swing_ride", 0), ("16beat", .5), ("bossa", .5), ("bongo_8beat", .5)])
def test_real_renderer_drum_onsets_agree_with_compiler_without_double_shuffle(tmp_path, monkeypatch, groove, swing):
    song = design("rhythm", groove)
    song["swing"] = swing
    song = load(tmp_path, song)
    events = render.compile_song(song)["rhythm"]["generated"]
    calls, placements = [], []
    monkeypatch.setattr(render, "get_drum", lambda voice: lambda velocity:
                        calls.append((voice, velocity)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: placements.append(start) or buf)
    render.render_part(song["parts"][0], song)
    assert calls == [(voice, vel) for _, voice, vel in events]
    expected = []
    for beat, _, _ in events:
        # Dの純粋検証と同じ承認式を、実renderer呼び出しとは独立に照合する。
        q = beat / .5
        moved = beat + swing * .5 / 3 if abs(q - round(q)) < 1e-6 and round(q) % 2 else beat
        assert render._swing(beat, song) == moved
        expected.append(int(moved * .5 * render.SR))
    assert placements == expected
    if groove in ("shuffle", "swing_ride"):
        assert any(beat == pytest.approx(1 + 2/3) for beat, _, _ in events)
        assert placements == [int(beat * .5 * render.SR) for beat, _, _ in events]


@pytest.mark.parametrize("role,pattern,meter,change", [
    ("chords", "waltz", "4/4", {}), ("rhythm", "shuffle", "4/4", {"swing": .1}),
    ("rhythm", "swing_ride", "4/4", {"swing": -.1}), ("rhythm", "16beat", "3/4", {}),
    ("rhythm", "16beat", "4/4", {"swing": 5}), ("chords", "strum", "4/4", {"strum": float("nan")}),
    ("rhythm", "bongo_8beat", "4/4", {"kit": ["kick"]}),
    ("rhythm", "swing_ride", "4/4", {"voices": {"bad": {}}}),
    ("rhythm", "shuffle", "4/4", {"sections": [], "swing": .1}),
    ("chords", "arpeggio_up", "4/4", {"bars": []}),
    ("bass", "arpeggio", "4/4", {"octave": True}),
    ("bass", "walking", "4/4", {"sections": ["unknown"]}),
])
@pytest.mark.parametrize("command", ["render", "listen"])
def test_rejections_precede_audio_cache_output_and_listener(tmp_path, monkeypatch, role, pattern, meter, change, command):
    song = design(role, pattern, meter)
    for key, value in change.items():
        (song if key in ("swing", "swing_unit") else song["parts"][0])[key] = value
    (tmp_path / "song.json").write_text(json.dumps(song), encoding="utf-8")

    def forbidden(*_, **__):
        pytest.fail("検証前に副作用が発生した")

    for name in ("get_instrument", "get_drum", "part_hash"):
        monkeypatch.setattr(render, name, forbidden)
    with pytest.raises(render.SongError):
        render.render_song(str(tmp_path), mp3=False)
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "bgm", command, str(tmp_path)],
                            capture_output=True, encoding="utf-8", timeout=15)
    assert result.returncode != 0
    assert "Traceback" not in result.stdout + result.stderr
    assert "[generated]" in result.stdout + result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.json"]


@pytest.mark.parametrize("role,pattern", [("bass", s) for s in BASS] + [("chords", s) for s in CHORDS])
def test_occurrence_selection_and_fractional_boundaries(tmp_path, role, pattern):
    song = design(role, pattern, "3/4")
    song["parts"][0]["sections"] = ["A"]
    compiled = render.compile_song(load(tmp_path, song))
    events = compiled["notes"]["generated"]
    assert all(0 <= beat < 3 or 6 <= beat < 9 for beat, *_ in events)
    first = [e for e in events if e[0] < 3]
    repeated = [(b - 6, p, d, v) for b, p, d, v in events if 6 <= b < 9]
    assert first == repeated
    for beat, _, duration, _ in events:
        harmony = next(c for c in reversed(compiled["harmony"]) if c["beat"] <= beat)
        assert beat + duration <= harmony["beat"] + harmony["duration"]
    original = copy.deepcopy(song)
    render.compile_song(song)
    assert song == original


@pytest.mark.parametrize("pattern", CHORDS)
@pytest.mark.parametrize("gate,strum,swing,humanize", [(9, .99, .7, .3), (-2, -.2, -.8, 2)])
def test_new_chords_hard_windows_after_all_timing(tmp_path, monkeypatch, pattern, gate, strum, swing, humanize):
    song = design(pattern=pattern, meter="3/4")
    song["swing"] = swing
    song["parts"][0].update(instrument="square", gate=gate, strum=strum, humanize=humanize, sections=["B", "A'"])
    song = load(tmp_path, song)
    calls, starts = [], []
    monkeypatch.setattr(render, "get_instrument", lambda *_: lambda midi, velocity, duration:
                        calls.append(duration) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: starts.append(start / render.SR) or buf)
    render.render_part(song["parts"][0], song)
    assert calls
    for onset, duration in zip(starts, calls, strict=True):
        assert duration > 0
        assert 1.5 - 1 / render.SR <= onset < 3 or 4.5 - 1 / render.SR <= onset < 6
        end = 3 if onset < 3 else min(5 + int((onset - 4.5) * 2) * .5, 6)
        assert onset + duration <= end + 1 / render.SR


@pytest.mark.parametrize("pattern", CHORDS)
def test_fractional_harmony_window_uses_original_attack_after_strum(tmp_path, monkeypatch, pattern):
    song = design(pattern=pattern, meter="3/4")
    song.update(form=["A"], sections={"A": {"bars": 1, "chords": "I ii iii IV V"}}, swing=.7)
    song["parts"][0].update(gate=100, strum=.09, humanize=.5)
    song = load(tmp_path, song)
    events = render.compile_song(song)["notes"]["generated"]
    calls, starts = [], []
    monkeypatch.setattr(render, "get_instrument", lambda *_: None)
    monkeypatch.setattr(synth, "render_pitched", lambda voice, midi, vel, duration, *, seed:
                        calls.append((midi, duration, seed)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: starts.append(start / render.SR) or buf)
    render.render_part(song["parts"][0], song)
    assert calls
    for (midi, duration, seed), onset in zip(calls, starts, strict=True):
        matches = [(beat, pitches) for beat, pitches, _, _ in events
                   if any(render._synth_seed("generated", "nylon_guitar", beat, 0, i, midi) == seed for i in range(3))]
        assert len(matches) == 1
        beat, _ = matches[0]
        chord = next(c for c in reversed(render.compile_song(song)["harmony"]) if c["beat"] <= beat)
        assert onset >= chord["beat"] * .5 - 1 / render.SR
        assert onset + duration <= (chord["beat"] + chord["duration"]) * .5 + 1 / render.SR


def test_valid_new_song_listener_serves_rendered_wav(tmp_path, monkeypatch):
    from threading import Thread
    from urllib.request import urlopen

    from bgm import __main__, listen

    song = design()
    load(tmp_path, song)
    render.render_song(str(tmp_path), mp3=False, log=lambda *_: None)
    audio = tmp_path / "batch3.wav"
    content = audio.read_bytes()

    def serve(selected, port):
        assert selected == audio
        with listen.make_server(selected, port=0) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/audio.wav") as response:
                    assert response.read() == content
            finally:
                server.shutdown()
                thread.join()

    monkeypatch.setattr(listen, "serve", serve)
    assert __main__.main(["listen", str(tmp_path)]) == 0
