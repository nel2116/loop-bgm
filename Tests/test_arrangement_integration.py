"""装飾と独立対旋律を共通の読み込み・描画・cache境界で検証する。"""

import copy
import json
import subprocess
import sys

import numpy as np
import pytest

from bgm import render, synth


def design(meter="4/4"):
    bpb = 4 if meter == "4/4" else 3
    return {"id": "arrangements", "usage": "video", "tempo": 120, "key": "C major", "meter": meter,
            "form": ["A", "B", "A", "A'"],
            "sections": {"A": {"bars": 1, "chords": "Iadd9/3 ii V"}, "B": {"bars": 1, "chords": "iv"}},
            "master": {"reverb": "none"},
            "parts": [{"name": "chain", "role": "arrange", "copy": "copy", "transpose": 2},
                      {"name": "copy", "role": "arrange", "copy": "melody", "octave": 1},
                      {"name": "counter", "role": "arrange", "accent": "counter", "source": "melody", "instrument": "kalimba"},
                      {"name": "sparkle", "role": "arrange", "accent": "phrase_start", "instrument": "kalimba"},
                      {"name": "tick", "role": "arrange", "accent": "offbeat_tick"},
                      {"name": "melody", "role": "melody", "instrument": "bass", "grid": "1/4",
                       "phrases": {"A": "3 - " + ". " * (bpb - 2), "B": ". " * bpb}, "sections": ["A", "B"]},
                      {"name": "independent", "role": "arrange", "instrument": "square", "bars": [f"G4:{bpb}" ]}]}


def load(tmp_path, song):
    (tmp_path / "song.json").write_text(json.dumps(song), encoding="utf-8")
    return render.load_song(str(tmp_path))[1]


def parts(song):
    return {p["name"]: p for p in song["parts"]}


@pytest.mark.parametrize("meter,offsets", [("4/4", [.5, 1.5, 2.5, 3.5]), ("3/4", [.5, 1.5, 2.5]), ("6/8", [.75, 2.25])])
def test_meter_graph_schedule_and_input_immutability(tmp_path, meter, offsets):
    raw = design(meter)
    original = copy.deepcopy(raw)
    compiled = render.compile_song(raw)
    assert raw == original
    song = load(tmp_path, raw)
    assert "instrument" not in parts(song)["copy"]
    assert compiled == render.compile_song(song)
    bpb = compiled["beats_per_bar"]
    assert [e[0] for e in compiled["rhythm"]["tick"]] == [bar * bpb + p for bar in range(4) for p in offsets]
    assert all(e[1:] == ("hat", 76) for e in compiled["rhythm"]["tick"])
    assert [e[0] for e in compiled["notes"]["sparkle"]] == [bar * bpb for bar in range(4)]
    assert compiled["notes"]["sparkle"][0] == (0, [74], .5, 108)
    assert [e[1][0] for e in compiled["notes"]["copy"]] == [76, 76]
    assert [e[1][0] for e in compiled["notes"]["chain"]] == [78, 78]
    assert not any(e[0] >= 3 * bpb for e in compiled["notes"]["counter"])
    assert all(e[0] >= 2 for e in compiled["notes"]["counter"])
    assert compiled["effective_parts"]["chain"]["instrument"] == "bass"


@pytest.mark.parametrize("meter,strong", [("4/4", [0, 2]), ("3/4", [0]), ("6/8", [0, 1.5])])
def test_counter_all_rest_is_real_rest_and_strong_beats(tmp_path, meter, strong):
    raw = design(meter)
    bpb = 4 if meter == "4/4" else 3
    raw.update(form=["B"], sections={"B": {"bars": 1, "chords": "I"}})
    parts(raw)["melody"].update(sections=["B"])
    events = render.compile_song(load(tmp_path, raw))["notes"]["counter"]
    assert events == [(p / 2, [60], .4, 90 if p / 2 in strong else 72) for p in range(bpb * 2)]


@pytest.mark.parametrize("notation", ["phrases", "bars"])
def test_independent_countermelody_overlaps_and_uses_direct_dsp(tmp_path, monkeypatch, notation):
    raw = design()
    independent = parts(raw)["independent"]
    independent.update(humanize=0, reverb=0, gate=.5, strum=.02)
    if notation == "phrases":
        independent.pop("bars")
        independent.update(grid="1/4", phrases={"A": "[1 5] - - -", "B": "[2 6] - - -"})
    song = load(tmp_path, raw)
    calls, starts = [], []
    monkeypatch.setattr(render, "get_instrument", lambda _: lambda m, v, d: calls.append((m, v, d)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: starts.append(start) or buf)
    render.render_part(parts(song)["independent"], song)
    compiled = render.compile_song(song)
    assert compiled["notes"]["melody"][0][0] == compiled["notes"]["independent"][0][0]
    assert all(c[2] == 1 for c in calls)
    assert starts[0] == 0
    if notation == "phrases":
        assert starts[1] == int(.02 * render.SR)


@pytest.mark.parametrize("kind", ["phrase_start", "counter", "style"])
def test_copy_chains_preserve_hard_windows_and_tone_indices(tmp_path, monkeypatch, kind):
    raw = design()
    p = parts(raw)
    source = p["sparkle"] if kind == "phrase_start" else p["counter"]
    if kind == "style":
        source = {"name": "chords", "role": "chords", "style": "broken", "instrument": "nylon_guitar", "transpose": 2}
        raw["parts"].append(source)
    p["copy"].update(copy=source["name"], gate=100, strum=-.03, humanize=0, reverb=0)
    p["chain"].update(gate=100, strum=-.03, humanize=0, reverb=0)
    song = load(tmp_path, raw)
    compiled = render.compile_song(song)
    calls, starts = [], []
    monkeypatch.setattr(render, "get_instrument", lambda _: None)
    monkeypatch.setattr(synth, "render_pitched", lambda voice, midi, velocity, duration, *, seed:
                        calls.append((midi, duration, seed)) or np.zeros((1, 2), np.float32))
    monkeypatch.setattr(render, "place", lambda buf, audio, start: starts.append(start) or buf)
    render.render_part(parts(song)["chain"], song)
    expected = []
    for event, meta in zip(compiled["notes"]["chain"], compiled["event_metadata"]["chain"], strict=True):
        beat, pitches, _, _ = event
        for k, midi in enumerate(pitches):
            start, end = meta["window"]
            onset = max(start * .5, beat * .5 - k * .03)
            if onset >= end * .5:
                continue
            expected.append((midi, end * .5 - onset,
                             render._synth_seed("chain", parts(song).get("chords", source)["instrument"], beat,
                                                meta["ordinal"], meta["tones"][k], midi)))
    assert calls == expected
    assert compiled["event_metadata"]["copy"] == compiled["event_metadata"]["chain"]


def test_source_dsp_not_inherited_or_applied_twice(tmp_path, monkeypatch):
    raw = design()
    parts(raw)["melody"].update(octave=1, transpose=2, gate=.01, strum=4, humanize=3, reverb=.9, volume=.01, pan=.7, mute=True)
    parts(raw)["copy"].update(instrument="square", gate=.5, humanize=0, reverb=0)
    song = load(tmp_path, raw)
    compiled = render.compile_song(song)
    assert compiled["notes"]["copy"][0] == (0, [90], 2, 90)
    assert compiled["notes"]["counter"][0][0] == 2
    assert "volume" not in compiled["effective_parts"]["copy"]
    calls = []
    monkeypatch.setattr(render, "get_instrument", lambda _: lambda m, v, d: calls.append((m, v, d)) or np.zeros((1, 2), np.float32))
    render.render_part(parts(song)["copy"], song)
    assert calls == [(90, 90, .5), (90, 90, .5)]


@pytest.mark.parametrize("mutation", ["unknown", "cycle", "conflict", "instrument", "null", "meter", "source", "velocity", "tick"])
@pytest.mark.parametrize("command", ["render", "listen"])
def test_cli_errors_before_audio_output_cache_or_server(tmp_path, mutation, command):
    raw = design()
    p = parts(raw)
    p["copy"]["sections"] = []
    if mutation == "unknown":
        p["copy"]["copy"] = "missing"
    elif mutation == "cycle":
        p["copy"]["copy"] = "chain"
    elif mutation == "conflict":
        p["copy"]["bars"] = None
    elif mutation == "instrument":
        p["copy"]["instrument"] = "missing"
    elif mutation == "null":
        p["copy"]["instrument"] = None
    elif mutation == "meter":
        raw["meter"] = "5/4"
        p["melody"].update(phrases={"A": ". . . . .", "B": ". . . . ."})
        p["independent"]["bars"] = ["G4:5"]
    elif mutation == "source":
        p["sparkle"]["source"] = "melody"
    elif mutation == "velocity":
        p["copy"]["velocity"] = 90
    else:
        p["tick"]["kit"] = ["ride"]
    (tmp_path / "song.json").write_text(json.dumps(raw), encoding="utf-8")
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "bgm", command, str(tmp_path)],
                            capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "小節" in result.stderr and "[" in result.stderr
    assert set(p.name for p in tmp_path.iterdir()) == {"song.json"}


def test_dependency_hashes_are_local_and_effective_instrument_is_hashed(tmp_path):
    song = load(tmp_path, design())

    def hashes(s):
        return {p["name"]: render.part_hash(p, s) for p in s["parts"]}

    reference = hashes(song)
    changed = copy.deepcopy(song)
    for p in changed["parts"]:
        p.update(volume=.1, pan=.3, mute=True)
    assert hashes(changed) == reference
    changed["parts"].insert(0, {"name": "extra", "instrument": "square", "bars": ["C4:4"]})
    assert all(hashes(changed)[k] == v for k, v in reference.items())
    changed = copy.deepcopy(song)
    parts(changed)["melody"]["instrument"] = "kalimba"
    assert {k for k, v in hashes(changed).items() if v != reference[k]} == {"melody", "copy", "chain"}
    changed = copy.deepcopy(song)
    parts(changed)["melody"]["phrases"]["A"] = "3 . . ."
    assert {k for k, v in hashes(changed).items() if v != reference[k]} == {"melody", "copy", "chain", "counter"}


def test_absolute_source_selection_and_no_sustain_reattack(tmp_path):
    raw = design()
    melody = parts(raw)["melody"]
    melody.pop("phrases")
    melody.pop("grid")
    melody.update(bars=["C4:8"], sections=["A"])
    parts(raw)["copy"].update(sections=["B"])
    compiled = render.compile_song(load(tmp_path, raw))
    assert [e[0] for e in compiled["notes"]["melody"]] == [0, 8]
    assert compiled["notes"]["copy"] == []
    assert compiled["notes"]["counter"] == []


def test_empty_selection_still_checks_direct_source_notation(tmp_path):
    raw = design()
    parts(raw)["melody"].update(sections=[], phrases={"A": "INVALID", "B": ". . . ."})
    with pytest.raises(render.SongError, match="melody"):
        load(tmp_path, raw)


def test_unselected_missing_phrase_is_optional_but_written_phrase_is_checked(tmp_path):
    raw = design()
    raw["form"] = ["A", "B"]
    melody = parts(raw)["melody"]
    melody.update(sections=["A"], phrases={"A": "1 . . ."})
    assert render.compile_song(load(tmp_path, raw))["notes"]["melody"] == [(0, [60], 1, 90)]
    melody["phrases"]["B"] = "INVALID"
    with pytest.raises(render.SongError, match="melody"):
        load(tmp_path, raw)
    melody.update(sections=["B"], phrases={"A": "1 . . ."})
    with pytest.raises(render.SongError, match="melody"):
        load(tmp_path, raw)


def test_adding_and_removing_arrangement_invalidates_selected_absolute_cache(tmp_path):
    raw = design()
    raw["form"] = ["A", "B"]
    raw["parts"] = [{"name": "absolute", "instrument": "square", "bars": ["C4:4"], "sections": ["A"]}]
    hashes = []
    for arranged in (False, True, False):
        raw["parts"] = raw["parts"][:1]
        if arranged:
            raw["parts"].append({"name": "tick", "role": "arrange", "accent": "offbeat_tick"})
        song = load(tmp_path, raw)
        hashes.append(render.part_hash(song["parts"][0], song))
        render.render_song(str(tmp_path), mp3=False, log=lambda *_: None)
        stem = tmp_path / "stems/absolute.wav"
        cached = stem.read_bytes()
        render.render_song(str(tmp_path), force=True, mp3=False, log=lambda *_: None)
        assert cached == stem.read_bytes()
    assert hashes[0] != hashes[1]
    assert hashes[0] == hashes[2]


def test_fractional_harmony_and_exact_counter_gaps(tmp_path):
    raw = design()
    melody = parts(raw)["melody"]
    melody.pop("phrases")
    melody.pop("grid")
    melody.update(bars=["r:0.25 C4:0.5 r:3.25"], sections=["A"])
    compiled = render.compile_song(load(tmp_path, raw))
    events = compiled["notes"]["counter"]
    expected = [.75, 4/3, 4/3 + .5, 8/3, 8/3 + .5]
    assert [e[0] for e in events] == pytest.approx(expected + [e + 8 for e in expected])
    assert [e[1] for e in events[:5]] == [[60], [62], [62], [67], [67]]
    assert compiled["event_metadata"]["counter"][0]["window"] == pytest.approx([.75, 4/3])


@pytest.mark.parametrize("gate", [-1, .001, 100])
def test_twenty_ms_minimum_clips_without_enlargement(tmp_path, monkeypatch, gate):
    raw = design()
    raw["sections"]["A"]["chords"] = " ".join(["I"] * 257)
    sparkle = parts(raw)["sparkle"]
    sparkle.update(gate=gate, humanize=0, reverb=0)
    song = load(tmp_path, raw)
    calls = []
    monkeypatch.setattr(render, "get_instrument", lambda _: None)
    monkeypatch.setattr(synth, "render_pitched", lambda *args, **kwargs: calls.append(args[3]) or np.zeros((1, 2), np.float32))
    render.render_part(parts(song)["sparkle"], song)
    assert calls[0] == pytest.approx(2 / 257)
    assert calls[-1] == pytest.approx(2 / 257)


def test_destination_swing_applies_once_clamps_skips_and_preserves_release(tmp_path, monkeypatch):
    raw = design()
    raw["swing"] = 3
    raw["parts"] = [p for p in raw["parts"] if p["name"] != "tick"]
    melody = parts(raw)["melody"]
    melody.pop("phrases")
    melody.pop("grid")
    melody.update(bars=["C4:0.5 r:0.5 C4:3"], sections=["A"])
    response = parts(raw)["counter"]
    response.update(humanize=0, reverb=0, gate=2)
    song = load(tmp_path, raw)
    calls = []
    monkeypatch.setattr(render, "get_instrument", lambda _: None)
    monkeypatch.setattr(synth, "render_pitched", lambda *args, **kwargs: calls.append(args) or np.zeros((1000, 2), np.float32))
    render.render_part(parts(song)["counter"], song)
    # .5開始の休みは1拍まで。swing後は境界に達するのでDSPも呼ばれない。
    assert calls == []


@pytest.mark.parametrize("field,value", [("accent", None), ("accent", "unknown"), ("accent", []), ("role", "melody"),
                                        ("type", None), ("type", "drums"), ("kit", []), ("voices", {}),
                                        ("bars", []), ("phrases", {}), ("grid", None), ("style", None),
                                        ("groove", None), ("source", "melody"), ("sections", None),
                                        ("octave", True), ("transpose", .5), ("velocity", 0)])
def test_phrase_start_invalid_fields_even_empty_selection(tmp_path, field, value):
    raw = design()
    parts(raw)["sparkle"].update(sections=[])
    parts(raw)["sparkle"][field] = value
    with pytest.raises(render.SongError, match=r"\[sparkle\].*小節"):
        load(tmp_path, raw)


@pytest.mark.parametrize("source", ["melody", "independent", "bass", "chords", "legacy", "copy"])
def test_copy_all_pitched_roles_and_explicit_range_transform(tmp_path, source):
    raw = design()
    raw["parts"].extend([{"name": "bass", "role": "bass", "style": "root_whole", "instrument": "bass"},
                         {"name": "chords", "role": "chords", "style": "pad", "instrument": "pad"},
                         {"name": "legacy", "instrument": "square", "bars": ["C4+E4+G4:4"]}])
    parts(raw)["chain"].update(copy=source, instrument="xylophone", octave=10, transpose=2)
    compiled = render.compile_song(load(tmp_path, raw))
    low, high = render.SAMPLED["xylophone"]["range"]
    for event, original in zip(compiled["notes"]["chain"], compiled["notes"][source], strict=True):
        assert all(low <= p <= high for p in event[1])
        assert [(p - q) % 12 for p, q in zip(event[1], original[1], strict=True)] == [2] * len(original[1])
        assert [p - event[1][0] for p in event[1]] == [p - original[1][0] for p in original[1]]


def test_simultaneous_duplicates_and_tone_indices_survive_selection_and_chain(tmp_path, monkeypatch):
    raw = design()
    parts(raw)["copy"].update(copy="independent", humanize=0, reverb=0)
    parts(raw)["chain"].update(instrument="kalimba", humanize=0, reverb=0)
    song = load(tmp_path, raw)
    original = render.arrangement._metadata

    def with_duplicates(part, events, compiled, source_events=()):
        if part["name"] == "independent":
            events[:] = [(0, [60, 60, 64], 1, 90), (0, [60, 60, 64], 1, 90)]
        return original(part, events, compiled, source_events)

    monkeypatch.setattr(render.arrangement, "_metadata", with_duplicates)
    compiled = render.compile_song(song)
    assert [m["ordinal"] for m in compiled["event_metadata"]["chain"]] == [0, 1]
    calls = []
    monkeypatch.setattr(render, "get_instrument", lambda _: None)
    monkeypatch.setattr(synth, "render_pitched", lambda *args, **kwargs: calls.append(kwargs["seed"]) or np.zeros((1, 2), np.float32))
    render.render_part(parts(song)["chain"], song)
    assert calls == [render._synth_seed("chain", "kalimba", 0, ordinal, k, pitch)
                     for ordinal in (0, 1) for k, pitch in enumerate([74, 74, 78])]


def test_source_dsp_changes_do_not_change_dependent_hashes(tmp_path):
    song = load(tmp_path, design())
    hashes = {name: render.part_hash(parts(song)[name], song) for name in ("copy", "chain", "counter")}
    changed = copy.deepcopy(song)
    parts(changed)["melody"].update(gate=.01, humanize=2, strum=.5, reverb=.8)
    assert {name: render.part_hash(parts(changed)[name], changed) for name in hashes} == hashes
