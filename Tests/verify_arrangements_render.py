"""装飾統合・旧音声の最終回帰を現在repoとGitだけから再現する。"""

import argparse
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

# 借用Pythonのeditable installより、必ずこのcheckoutを優先する。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bgm import render  # noqa: E402
from Tests.verify_accompaniment_render import arrays, exact, write_design  # noqa: E402
from Tests.verify_patterns_render import seam, stamps  # noqa: E402

BASELINE = "738b9809e48d813eea648f40ccd13841b19e92ae"


def run(command, log, *, cwd=ROOT, checkout=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout or cwd)
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, encoding="utf-8")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps(command, ensure_ascii=False) + "\n" + result.stdout + result.stderr, encoding="utf-8")
    result.check_returncode()
    return command


def cli(folder, *, checkout=ROOT, force=True):
    return run([sys.executable, "-X", "utf8", "-m", "bgm", "render", str(folder), "--no-mp3", *(["--force"] if force else [])],
               folder / ("force-cli.log" if force else "cache-cli.log"), cwd=checkout)


def snapshot(folder):
    _, song = render.load_song(str(folder))
    compiled = render.compile_song(song)
    (folder / "events.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    return song, compiled


def verify_design(folder, design):
    write_design(folder, design)
    report = {"command": cli(folder), "comparisons": {}}
    reference = arrays(folder, design)
    song, compiled = snapshot(folder)
    report["loops"] = {name: seam(audio) for name, audio in reference.items()}
    for label in ("force", "force_again"):
        render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
        report["comparisons"][label] = exact(reference, arrays(folder, design))
    other = copy.deepcopy(design)
    other.update(id="interleaved", key="D minor")
    write_design(folder / "interleaved", other)
    render.render_song(str(folder / "interleaved"), force=True, mp3=False, log=lambda *_: None)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["interleaved"] = exact(reference, arrays(folder, design))
    cache = folder / "stems/cache.json"
    hashes = json.loads(cache.read_text(encoding="utf-8"))
    times = stamps(folder)
    partial = {name: value for name, value in hashes.items() if name not in ("melody", "melody_hi", "response")}
    cache.write_text(json.dumps(partial), encoding="utf-8")
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    report["comparisons"]["partial_cache"] = exact(reference, arrays(folder, design))
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    assert all(stamps(folder)[name + ".wav"] == times[name + ".wav"] for name in partial)
    report["separate_process"] = cli(folder)
    report["comparisons"]["process"] = exact(reference, arrays(folder, design))
    times = stamps(folder)
    mixed = copy.deepcopy(design)
    for part in mixed["parts"]:
        part.update(volume=.17, pan=.23, mute=True)
    write_design(folder, mixed)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    assert stamps(folder) == times
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    exact({k: v for k, v in reference.items() if k != "mix"}, {k: v for k, v in arrays(folder, design).items() if k != "mix"})
    report["mix_only_hash_mtime_stems_equal"] = True
    inserted = copy.deepcopy(design)
    inserted["parts"].insert(0, {"name": "extra", "instrument": "square", "bars": [f"C4:{compiled['beats_per_bar']}"], "mute": True})
    write_design(folder, inserted)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    assert all(stamps(folder)[name + ".wav"] == times[name + ".wav"] for name in hashes)
    report["comparisons"]["extra_part"] = exact(reference, arrays(folder, design))
    write_design(folder, design)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    for label, field, value, affected in (
        ("source_notes", "phrases", {"A": "3 . . . . . . ." if design["meter"] == "4/4" else "3 . . . . .",
                                     "B": ". . . . . . . ." if design["meter"] == "4/4" else ". . . . . ."},
         {"melody", "melody_hi", "response"}),
        ("source_instrument", "instrument", "kalimba", {"melody", "melody_hi"}),
    ):
        edited = copy.deepcopy(design)
        next(p for p in edited["parts"] if p["name"] == "melody")[field] = value
        write_design(folder, edited)
        prior_times = stamps(folder)
        render.render_song(str(folder), mp3=False, log=lambda *_: None)
        after = json.loads(cache.read_text(encoding="utf-8"))
        assert {name for name in hashes if hashes[name] != after[name]} == affected
        assert all(stamps(folder)[name + ".wav"] == prior_times[name + ".wav"] for name in hashes.keys() - affected)
        changed = arrays(folder, edited)
        assert all(not np.array_equal(reference[name], changed[name]) for name in affected)
        snapshot(folder)
        saved = folder / label
        shutil.copytree(folder / "stems", saved / "stems", dirs_exist_ok=True)
        shutil.copy2(folder / "events.json", saved / "events.json")
        (saved / "out").mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / "out" / f"{design['id']}.wav", saved / "out" / f"{design['id']}.wav")
        write_design(saved, edited)
        report[label] = sorted(affected)
        write_design(folder, design)
        render.render_song(str(folder), mp3=False, log=lambda *_: None)
    minor = copy.deepcopy(design)
    minor["key"] = "C minor"
    write_design(folder / "minor", minor)
    cli(folder / "minor")
    _, minor_compiled = snapshot(folder / "minor")
    minor_audio = arrays(folder / "minor", minor)
    # Iadd9/3の実最高音Dは長短調で同じ。Bの明示ivも同じなので句頭音は不変。
    equal = ("absolute", "absolute_copy", "sparkle", "tick", "direct_drums")
    for name, audio in reference.items():
        assert np.array_equal(audio, minor_audio[name]) == (name in equal), name
    assert compiled["notes"]["absolute_copy"] == minor_compiled["notes"]["absolute_copy"]
    assert compiled["notes"]["melody"][0][1] == [64]
    assert minor_compiled["notes"]["melody"][0][1] == [63]
    report["key_only_equal"] = list(equal)
    report["minor_loops"] = {name: seam(audio) for name, audio in minor_audio.items()}
    before = copy.deepcopy(design)
    before["parts"] = [p for p in before["parts"] if "copy" not in p and "accent" not in p]
    write_design(folder / "before", before)
    cli(folder / "before")
    snapshot(folder / "before")
    before_audio = arrays(folder / "before", before)
    for name in before_audio.keys() - {"mix"}:
        assert np.array_equal(reference[name], before_audio[name]), name
    report["before_basis"] = "同じ曲から新生成copy/accentのみを除く。直接記述の独立対旋律は両方に残す。"
    report["before_after_wavs"] = [str(folder / "before/out" / f"{design['id']}.wav"), str(folder / "out" / f"{design['id']}.wav")]
    report["before_loop"] = seam(before_audio["mix"])
    snapshot(folder)
    exact(reference, arrays(folder, design))
    return report


def legacy(output, scratch):
    report = {"baseline": BASELINE, "songs": {}}
    code = "import bgm.render; print(bgm.render.__file__)"
    imported = subprocess.check_output([sys.executable, "-c", code], cwd=scratch,
                                       env=dict(os.environ, PYTHONPATH=str(scratch)), text=True).strip()
    assert Path(imported).resolve() == scratch / "bgm/render.py"
    report["historical_import_verified"] = True
    report["numeric"] = legacy_numeric(output, scratch)
    for name in ("phase1_degrees", "phase1_accompaniment", "phase1_patterns"):
        design = json.loads((ROOT / "songs" / name / "song.json").read_text(encoding="utf-8"))
        before, after = output / name / "before", output / name / "after"
        write_design(before, design)
        write_design(after, design)
        cli(before, checkout=scratch)
        cli(after)
        equality = exact(arrays(before, design), arrays(after, design))
        assert json.loads((before / "stems/cache.json").read_text()) == json.loads((after / "stems/cache.json").read_text())
        _, current = snapshot(after)
        code = "import json,sys; from bgm.render import load_song,compile_song; print(json.dumps(compile_song(load_song(sys.argv[1])[1])))"
        result = subprocess.check_output([sys.executable, "-X", "utf8", "-c", code, str(before)], cwd=scratch,
                                         env=dict(os.environ, PYTHONPATH=str(scratch)), encoding="utf-8")
        (before / "events.json").write_text(result, encoding="utf-8")
        assert json.loads(result) == json.loads(json.dumps(current))
        report["songs"][name] = {"arrays": equality, "hashes_equal": True, "compiled_equal": True}
    # 以前は受理されても無視されたcopy/accentを実cacheで確認する。
    # 旧コードは usage を読まない。今のコードは usage を必須とする(#75)。
    design = {"id": "ignored", "usage": "video", "tempo": 180, "key": "C major", "meter": "4/4", "form": ["A"],
              "sections": {"A": {"bars": 1, "chords": "I"}}, "master": {"reverb": "none"},
              "parts": [{"name": "source", "instrument": "square", "bars": ["C4:4"], "humanize": 0, "reverb": 0},
                        {"name": "copy", "role": "arrange", "copy": "source", "instrument": "square", "humanize": 0, "reverb": 0},
                        {"name": "sparkle", "role": "arrange", "accent": "phrase_start", "instrument": "square",
                         "humanize": 0, "reverb": 0}]}
    folder = output / "ignored-cache"
    write_design(folder, design)
    cli(folder, checkout=scratch)
    before = arrays(folder, design)
    hashes = json.loads((folder / "stems/cache.json").read_text())
    shutil.copytree(folder / "stems", folder / "before/stems", dirs_exist_ok=True)
    shutil.copy2(folder / "ignored.wav", folder / "before/ignored.wav")
    cli(folder, force=False)
    after = arrays(folder, design)
    changed = json.loads((folder / "stems/cache.json").read_text())
    assert {name for name in hashes if hashes[name] != changed[name]} == {"copy", "sparkle"}
    assert np.array_equal(before["source"], after["source"])
    assert not np.any(before["copy"]) and np.any(after["copy"])
    assert not np.any(before["sparkle"]) and np.any(after["sparkle"])
    cli(folder)
    report["ignored_cache"] = {"before_hashes": hashes, "after_hashes": changed, "invalidated": ["copy", "sparkle"],
                               "normal_force_equal": exact(after, arrays(folder, design)),
                               "revision_needed": False, "reason": "実イベント・境界・実効楽器のhashで区別できるため専用revision不要"}
    return report


def legacy_numeric(output, scratch):
    cases = []
    for meter in ("4/4", "3/4", "6/8"):
        for role, styles in (("bass", ("root_whole", "root_quarter", "root_fifth", "octave_8th", "walking", "arpeggio")),
                             ("chords", ("pad", "block", "offbeat", "arpeggio_up", "broken", "strum", "waltz"))):
            for style in styles:
                if style == "waltz" and meter != "3/4":
                    continue
                for selected in (["A"], ["A'"], [], None):
                    for key in ("C major", "C minor"):
                        part = {"name": "old", "role": role, "style": style, "instrument": "bass", "octave": 1, "transpose": 2}
                        if selected is not None:
                            part["sections"] = selected
                        cases.append({"id": "numeric", "usage": "video", "tempo": 180, "key": key, "meter": meter,
                                      "form": ["A", "B", "A", "A'"], "master": {"reverb": "none"},
                                      "sections": {"A": {"bars": 1, "chords": "Iadd9/3 iii V"}, "B": {"bars": 1, "chords": "iv"}},
                                      "parts": [part]})
    pitched_count = len(cases)
    grooves = {"4/4": ("8beat", "16beat", "shuffle", "bossa", "march", "swing_ride", "bongo_8beat", "ambient_none"),
               "3/4": ("waltz", "ambient_none"), "6/8": ("march", "ambient_none")}
    for meter, patterns in grooves.items():
        for groove in patterns:
            case = copy.deepcopy(cases[0])
            case["meter"] = meter
            case["parts"] = [{"name": "old", "role": "rhythm", "groove": groove}]
            cases.append(case)
    output.mkdir(parents=True, exist_ok=True)
    folders = []
    for index, design in enumerate(cases):
        folder = output / "numeric" / str(index)
        write_design(folder, design)
        folders.append(str(folder))
    payload = output / "numeric-input.json"
    payload.write_text(json.dumps(folders), encoding="utf-8")
    current = []
    for folder in folders:
        _, song = render.load_song(folder)
        current.append({"compiled": render.compile_song(song), "hashes": [render.part_hash(p, song) for p in song["parts"]]})
    code = ("import json,sys; from bgm.render import load_song,compile_song,part_hash; "
            "songs=[load_song(f)[1] for f in json.load(open(sys.argv[1]))]; "
            "print(json.dumps([{'compiled':compile_song(s),'hashes':[part_hash(p,s) for p in s['parts']]} for s in songs]))")
    old = subprocess.check_output([sys.executable, "-X", "utf8", "-c", code, str(payload)], cwd=scratch,
                                  env=dict(os.environ, PYTHONPATH=str(scratch)), encoding="utf-8")
    (output / "numeric-before.json").write_text(old, encoding="utf-8")
    (output / "numeric-after.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    assert json.loads(old) == json.loads(json.dumps(current))
    audio_cases = [i for i, case in enumerate(cases)
                   if (i < pitched_count and i % 8 == 6
                       or i >= pitched_count and case["parts"][0]["groove"] not in ("swing_ride", "bongo_8beat"))]
    audio_folders = []
    for index in audio_cases:
        folder = output / "style-audio" / str(index)
        write_design(folder, cases[index])
        audio_folders.append(str(folder))
    payload = output / "style-audio-input.json"
    payload.write_text(json.dumps(audio_folders), encoding="utf-8")
    code = ("import json,sys; from bgm.render import render_song; "
            "[render_song(f,force=True,mp3=False) for f in json.load(open(sys.argv[1]))]")
    run([sys.executable, "-X", "utf8", "-c", code, str(payload)], output / "style-audio-before.log", cwd=scratch)
    audio_report = {}
    for index, folder_name in zip(audio_cases, audio_folders, strict=True):
        folder, design = Path(folder_name), cases[index]
        before = arrays(folder, design)
        shutil.copytree(folder / "stems", folder / "before/stems", dirs_exist_ok=True)
        shutil.copy2(folder / "numeric.wav", folder / "before/numeric.wav")
        render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
        after = arrays(folder, design)
        snapshot(folder)
        part = design["parts"][0]
        name = design["meter"] + ":" + part.get("style", part.get("groove"))
        audio_report[name] = {"arrays": exact(before, after), "loops": {k: seam(v) for k, v in after.items()}}
    return {"cases": len(cases), "all_supported_styles_grooves_compiled_and_hashes_equal": True, "synth_style_audio": audio_report}


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "checkout": str(ROOT), "imported_bgm": str(Path(render.__file__).resolve()), "meters": {}}
    assert Path(render.__file__).resolve().parent == ROOT / "bgm"
    design = json.loads((ROOT / "songs/phase1_arrangements/song.json").read_text(encoding="utf-8"))
    for meter in ("4/4", "3/4", "6/8"):
        variant = copy.deepcopy(design)
        variant["meter"] = meter
        if meter != "4/4":
            next(p for p in variant["parts"] if p["name"] == "melody")["phrases"] = {"A": "3 - . 5 - .", "B": ". . . . . ."}
            next(p for p in variant["parts"] if p["name"] == "countermelody")["phrases"] = {"A": "1, - 3,", "B": "4, - 3,"}
            next(p for p in variant["parts"] if p["name"] == "absolute")["bars"] = ["C5:0.5 r:2.5"]
        report["meters"][meter] = verify_design(output / meter.replace("/", "-"), variant)
    archive = subprocess.check_output(["git", "archive", "--format=zip", BASELINE, "bgm"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="loopbgm-arrangement-") as temp:
        scratch = Path(temp)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            package.extractall(scratch)
        report["legacy"] = legacy(output / "legacy", scratch)
    # 旧helperの歴史bass差分・PCM再構成・全旧型の規則をそのまま維持する。
    report["regression_command"] = run([sys.executable, "-X", "utf8", str(ROOT / "Tests/verify_patterns_render.py"),
                                        "--output", str(output / "patterns")], output / "patterns.log")
    report["unverified"] = ["主観試聴と音楽的自然さ", "実サンプルswing_ride/bongo_8beat WAV", "実transfer-origin削除"]
    report["success"] = True
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"装飾統合の最終回帰 OK: {output / 'verification.json'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output.resolve())
