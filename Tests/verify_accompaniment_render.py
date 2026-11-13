"""伴奏統合のWAV、全イベント、決定性とキャッシュ検証を再現する。"""

import argparse
import copy
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from bgm import render

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "f4dd9e2"


def write_design(folder, design):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "song.json").write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")


def arrays(folder, design):
    # 過去のコミットで書き出した比較対は out/ ができる前の場所（曲フォルダ直下）にマスターがある。
    master = folder / "out" / f"{design['id']}.wav"
    files = {"mix": master if master.exists() else folder / f"{design['id']}.wav"}
    files.update({p["name"]: folder / "stems" / f"{p['name']}.wav" for p in design["parts"]})
    return {name: sf.read(path, dtype="float32", always_2d=True)[0] for name, path in files.items()}


def exact(before, after):
    assert before.keys() == after.keys()
    for name in before:
        assert np.array_equal(before[name], after[name]), f"全配列不一致: {name}"
    return {name: {"equal": True, "shape": list(audio.shape)} for name, audio in before.items()}


def cli(folder, log, cwd=ROOT):
    command = [sys.executable, "-X", "utf8", "-m", "bgm", "render", str(folder), "--force", "--no-mp3"]
    process = subprocess.run(command, cwd=cwd, capture_output=True, encoding="utf-8", check=True)
    log.write_text(process.stdout + process.stderr, encoding="utf-8")
    return command


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    design = json.loads((ROOT / "songs/phase1_accompaniment/song.json").read_text(encoding="utf-8"))
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "baseline": BASELINE, "comparisons": {}, "loops": {}, "commands": []}
    folder = output / "major"
    write_design(folder, design)
    report["commands"].append(cli(folder, output / "major-cli.log"))
    reference = arrays(folder, design)
    _, song = render.load_song(str(folder))
    compiled = render.compile_song(song)
    (output / "major-events.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["same_process_force"] = exact(reference, arrays(folder, design))
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["same_process_force_again"] = exact(reference, arrays(folder, design))
    other = copy.deepcopy(design)
    other["id"], other["key"] = "interleaved", "D minor"
    write_design(output / "interleaved", other)
    render.render_song(str(output / "interleaved"), force=True, mp3=False, log=lambda *_: None)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["interleaved"] = exact(reference, arrays(folder, design))
    cache = folder / "stems/cache.json"
    hashes = json.loads(cache.read_text(encoding="utf-8"))
    times = {p.name: p.stat().st_mtime_ns for p in (folder / "stems").glob("*.wav")}
    partial = dict(hashes)
    del partial["bass"]
    del partial["rhythm"]
    cache.write_text(json.dumps(partial), encoding="utf-8")
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    report["comparisons"]["partial_cache"] = exact(reference, arrays(folder, design))
    for name in ("melody", "chords", "absolute", "direct_drums"):
        assert (folder / "stems" / f"{name}.wav").stat().st_mtime_ns == times[f"{name}.wav"]
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    report["commands"].append(cli(folder, output / "separate-process-cli.log"))
    report["comparisons"]["separate_process"] = exact(reference, arrays(folder, design))
    times = {p.name: p.stat().st_mtime_ns for p in (folder / "stems").glob("*.wav")}
    mixed = copy.deepcopy(design)
    for part in mixed["parts"]:
        part.update(volume=.2, pan=.2)
    write_design(folder, mixed)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    assert times == {p.name: p.stat().st_mtime_ns for p in (folder / "stems").glob("*.wav")}
    report["mix_only_preserves_hash_and_mtime"] = True
    report["hash_dependencies"] = hash_dependencies(song)
    write_design(folder, design)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    exact(reference, arrays(folder, design))
    minor = copy.deepcopy(design)
    minor["key"] = "C minor"
    minor_folder = output / "minor"
    write_design(minor_folder, minor)
    report["commands"].append(cli(minor_folder, output / "minor-cli.log"))
    minor_audio = arrays(minor_folder, minor)
    _, minor_song = render.load_song(str(minor_folder))
    minor_compiled = render.compile_song(minor_song)
    (output / "minor-events.json").write_text(json.dumps(minor_compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("melody", "bass", "chords"):
        assert compiled["notes"][name] != minor_compiled["notes"][name]
        assert not np.array_equal(reference[name], minor_audio[name])
    for name in ("absolute", "rhythm", "direct_drums"):
        assert np.array_equal(reference[name], minor_audio[name])
    assert compiled["notes"]["absolute"] == minor_compiled["notes"]["absolute"]
    assert compiled["rhythm"] == minor_compiled["rhythm"]
    report["key_only"] = {"changed": ["melody", "bass", "chords"], "equal": ["absolute", "rhythm", "direct_drums"]}
    render.render_song(str(minor_folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["minor_force"] = exact(minor_audio, arrays(minor_folder, minor))
    # 伴奏追加前の比較対は同じ設計から生成3パートだけを除く。従来パートは旧HEADとも厳密比較する。
    before = copy.deepcopy(design)
    before["parts"] = [p for p in before["parts"] if "style" not in p and "groove" not in p]
    before_folder = output / "before-accompaniment"
    write_design(before_folder, before)
    archive = subprocess.check_output(["git", "archive", "--format=zip", BASELINE, "bgm"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="loopbgm-accompaniment-") as scratch:
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            package.extractall(scratch)
        report["commands"].append(cli(before_folder, output / "before-cli.log", cwd=scratch))
    old = arrays(before_folder, before)
    for name in ("melody", "absolute", "direct_drums"):
        assert np.array_equal(old[name], reference[name])
    report["baseline_untouched_stems_exact"] = ["melody", "absolute", "direct_drums"]
    for name, audio in (("before", old["mix"]), ("major", reference["mix"]), ("minor", minor_audio["mix"])):
        ok, message = render.check_loop(audio)
        report["loops"][name] = {"ok": bool(ok), "message": message}
    report["success"] = True
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def hash_dependencies(song):
    original = {p["name"]: render.part_hash(p, song) for p in song["parts"]}
    changes = {}
    for field in ("key", "form", "chords", "style", "groove", "volume", "pan"):
        variant = copy.deepcopy(song)
        if field == "key":
            variant["key"] = "C minor"
        elif field == "form":
            variant["form"] = ["B", "A", "A"]
        elif field == "chords":
            variant["sections"]["A"]["chords"] = "vi | IV V"
        elif field == "style":
            variant["parts"][1]["style"] = "root_quarter"
        elif field == "groove":
            variant["parts"][3]["groove"] = "march"
        else:
            for part in variant["parts"]:
                part[field] = .2
        updated = {p["name"]: render.part_hash(p, variant) for p in variant["parts"]}
        changed = sorted(name for name in original if original[name] != updated[name])
        if field in ("volume", "pan"):
            assert not changed
        elif field in ("style", "groove"):
            assert changed == (["bass"] if field == "style" else ["rhythm"])
        else:
            assert {"melody", "bass", "chords"}.issubset(changed)
        changes[field] = changed
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    verify(args.output.resolve())
    print(f"伴奏統合検証 OK: {args.output.resolve() / 'verification.json'}")
