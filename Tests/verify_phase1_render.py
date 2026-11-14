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

from bgm.paths import SR
from bgm.render import check_loop, compile_song, load_song, pan_gains, render_song

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


def _read_stereo(path):
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != SR or audio.shape[1] != 2 or not np.isfinite(audio).all():
        raise AssertionError(f"音声形式が不正: {path}")
    return audio


def _normalized_pcm_mix(stems, fixture):
    # FLOAT stemから元のパート順・音量・定位で合成し、PCM16書き出しも再現する。
    mix = np.zeros((max(len(a) for a in stems.values()), 2), np.float32)
    for part in fixture["parts"]:
        audio = stems[part["name"]]
        gains = np.array(pan_gains(part.get("pan", 0)), np.float32) * np.float32(part.get("volume", 0.8))
        mix[:len(audio)] += audio * gains
    target = 10 ** (-1 / 20) * 10 ** (min(0, fixture.get("master", {}).get("gain_db", 0)) / 20)
    peak = np.abs(mix).max()
    gain = target / peak if peak > 0 else 1.0
    mix *= np.float32(gain)
    stream = io.BytesIO()
    sf.write(stream, mix, SR, format="WAV", subtype="PCM_16")
    stream.seek(0)
    return sf.read(stream, dtype="float32", always_2d=True)[0], float(gain)


def compare_legacy(old, new, fixture):
    # この歴史的fixtureの意図した変更はbassだけ。その他の差分は許可しない。
    bass = [part for part in fixture["parts"] if part.get("instrument") == "bass"]
    if len(bass) != 1 or bass[0]["name"] != "bass":
        raise AssertionError("歴史的fixtureにbassパートが1つ必要です")
    regression, old_stems, new_stems = {}, {}, {}
    for part in fixture["parts"]:
        name = part["name"]
        before, after = old / "stems" / f"{name}.wav", new / "stems" / f"{name}.wav"
        left, right = _read_stereo(before), _read_stereo(after)
        if left.shape != right.shape:
            raise AssertionError(f"stemの形が不一致: {name}")
        old_stems[name], new_stems[name] = left, right
        if name == "bass":
            if np.array_equal(left, right):
                raise AssertionError("bassに意図したイベントseedの変更がありません")
            regression[name] = {"equal": False, "intentional_change": "#24: shared RNG → stable event seed",
                                "unequal_samples": int(np.count_nonzero(left != right)),
                                "max_abs_difference": float(np.max(np.abs(left - right)))}
        else:
            regression[name] = compare_audio(before, after)
    left_mix, right_mix = _read_stereo(old / "legacy_synth.wav"), _read_stereo(new / "out" / "legacy_synth.wav")
    # 非対象stemが同一なので、bassだけ置換したmixを同じ正規化で再構成できる必要がある。
    replaced = dict(old_stems, bass=new_stems["bass"])
    old_expected, old_gain = _normalized_pcm_mix(old_stems, fixture)
    new_expected, new_gain = _normalized_pcm_mix(replaced, fixture)
    if not np.array_equal(left_mix, old_expected) or not np.array_equal(right_mix, new_expected):
        raise AssertionError("mix差分をbass置換とピーク正規化だけでは説明できません")
    if np.array_equal(left_mix, right_mix):
        raise AssertionError("bass変更後のmixが旧版と同じです")
    regression["mix"] = {"equal": False, "explained_by_bass_and_normalization": True,
                         "old_gain": old_gain, "new_gain": new_gain,
                         "old_pcm_reconstructed_equal": True, "new_pcm_reconstructed_equal": True}
    return regression


def verify(output, baseline):
    output.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(["git", "show", f"{baseline}:Tests/test_engine.py"], cwd=ROOT).decode("utf-8")
    fixture = next(ast.literal_eval(node.value) for node in ast.parse(source).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYNTH_SONG" for t in node.targets))
    fixture["id"] = "legacy_synth"
    # #75 で usage が必須になった。旧コードは知らないキーを読まないので両方に同じ定義を渡せる。
    fixture["usage"] = "video"
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
    regression = compare_legacy(old, new, fixture)
    print("旧曲: 非対象stem全配列一致、bassの意図した変更と正規化でmix差分を説明")

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
