"""変更前コードとの全サンプル比較と、試聴用の長短調WAVを生成する。"""

import argparse
import ast
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from bgm.render import check_loop, compile_song, load_song, render_song

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "17dddfed1fbda3f105737307896f78ebdd56a910"


def write_design(folder, song):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "song.json").write_text(json.dumps(song, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_audio(before, after):
    left, sr = sf.read(before, dtype="float32", always_2d=True)
    right, other_sr = sf.read(after, dtype="float32", always_2d=True)
    if sr != other_sr or not np.array_equal(left, right):
        raise AssertionError(f"配列が不一致: {before} / {after}")
    return {"samples": len(left), "channels": left.shape[1], "equal": True}


def verify(output, baseline):
    output.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(["git", "show", f"{baseline}:Tests/test_engine.py"], cwd=ROOT).decode("utf-8")
    fixture = next(ast.literal_eval(node.value) for node in ast.parse(source).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYNTH_SONG" for t in node.targets))
    fixture["id"] = "legacy_synth"
    old, new = output / "legacy-before", output / "legacy-after"
    write_design(old, fixture)
    write_design(new, fixture)
    archive = subprocess.check_output(["git", "archive", "--format=zip", baseline, "bgm"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="loopbgm-baseline-") as scratch:
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            package.extractall(scratch)
        for cwd, folder in ((Path(scratch), old), (ROOT, new)):
            command = [sys.executable, "-m", "bgm", "render", str(folder), "--force", "--no-mp3"]
            subprocess.run(command, cwd=cwd, check=True)
    regression = {"mix": compare_audio(old / "legacy_synth.wav", new / "legacy_synth.wav")}
    for part in fixture["parts"]:
        file = f"{part['name']}.wav"
        regression[part["name"]] = compare_audio(old / "stems" / file, new / "stems" / file)
    print("旧曲: mix + 4 stems の全配列が変更前と一致")

    design = json.loads((ROOT / "songs/phase1_degrees/song.json").read_text(encoding="utf-8"))
    reports, arrays = {}, {}
    for mode in ("major", "minor"):
        design["key"] = f"C {mode}"
        folder = output / mode
        write_design(folder, design)
        _, loaded = load_song(str(folder))
        compiled = compile_song(loaded)
        out = render_song(str(folder), force=True, mp3=False)
        audio = sf.read(out, dtype="float32", always_2d=True)[0]
        stems = {p["name"]: sf.read(folder / "stems" / f"{p['name']}.wav", dtype="float32")[0] for p in design["parts"]}
        render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
        if not np.array_equal(audio, sf.read(out, dtype="float32", always_2d=True)[0]):
            raise AssertionError(f"{mode}: 強制再レンダーが不一致")
        for name, samples in stems.items():
            if not np.array_equal(samples, sf.read(folder / "stems" / f"{name}.wav", dtype="float32")[0]):
                raise AssertionError(f"{mode}/{name}: 強制再レンダーが不一致")
        ok, message = check_loop(audio)
        if not ok:
            raise AssertionError(message)
        reports[mode] = {"wav": str(out), "loop": message, "compiled": compiled, "force_equal": True}
        arrays[mode] = (audio, stems["absolute"])
        print(f"{mode}: {message} / force mix + stems 一致")
    if np.array_equal(arrays["major"][0], arrays["minor"][0]):
        raise AssertionError("長調と短調のWAVが同じです")
    if not np.array_equal(arrays["major"][1], arrays["minor"][1]):
        raise AssertionError("絶対音パートが調によって変化しました")
    thirds = [reports[mode]["compiled"]["notes"]["melody"][1][1][0] for mode in ("major", "minor")]
    if thirds != [64, 63]:
        raise AssertionError(f"第3音が期待値64→63と異なります: {thirds}")
    report = output / "verification.json"
    report.write_text(json.dumps({"baseline": baseline, "regression": regression, "modes": reports},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"第3音64→63、長短調WAV差あり、絶対音配列一致。検証結果: {report}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "songs/phase1_degrees/build/verification")
    parser.add_argument("--baseline", default=BASELINE)
    args = parser.parse_args()
    verify(args.output.resolve(), args.baseline)
