"""変化のCLI・cache・決定性をrepo内入力だけで再現する。"""

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bgm import render  # noqa: E402
from Tests.verify_accompaniment_render import arrays, exact, write_design  # noqa: E402
from Tests.verify_arrangements_render import cli, run, snapshot  # noqa: E402
from Tests.verify_patterns_render import seam, stamps  # noqa: E402


def variant(design, meter):
    result = copy.deepcopy(design)
    result["meter"] = meter
    if meter != "4/4":
        named = {p["name"]: p for p in result["parts"]}
        named["melody"]["phrases"] = {"A": "3 - 5 | 1 - -", "B": "4 - . | 5 - ."}
        named["countermelody"]["phrases"] = {"A": "1, - 3, | 5, - 3,", "B": "4, - 3, | 5, - 2,"}
        named["absolute"]["bars"] = ["C5:0.5 r:2.5"]
        named["held"]["bars"] = ["C4:9 r:3"]
        next(r for r in result["variation"] if r["do"] == "period")["beats"] = 4
    return result


def verify_design(folder, design):
    write_design(folder, design)
    report = {"cli": cli(folder), "comparisons": {}}
    song, compiled = snapshot(folder)
    reference = arrays(folder, design)
    report["loops"] = {name: seam(audio) for name, audio in reference.items()}
    report["changed_parts"] = compiled["variation_parts"]
    first_bytes = {p.name: p.read_bytes() for p in (folder / "stems").glob("*.wav")}
    # FLOAT PEAKの秒境界を実際に跨いだ強制描画でbyteも比較する。
    time.sleep(1.05)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["force"] = exact(reference, arrays(folder, design))
    assert first_bytes == {p.name: p.read_bytes() for p in (folder / "stems").glob("*.wav")}
    report["stem_wav_bytes_equal_across_seconds"] = True
    other = copy.deepcopy(design)
    other.update(id="interleaved", key="D minor")
    write_design(folder / "interleaved", other)
    render.render_song(str(folder / "interleaved"), force=True, mp3=False, log=lambda *_: None)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["interleaved"] = exact(reference, arrays(folder, design))
    cache = folder / "stems/cache.json"
    hashes = json.loads(cache.read_text(encoding="utf-8"))
    times = stamps(folder)
    partial = {n: v for n, v in hashes.items() if n not in ("melody", "melody_hi", "response", "arp")}
    cache.write_text(json.dumps(partial), encoding="utf-8")
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    report["comparisons"]["partial_cache"] = exact(reference, arrays(folder, design))
    assert json.loads(cache.read_text()) == hashes
    assert all(stamps(folder)[n + ".wav"] == times[n + ".wav"] for n in partial)
    report["separate_process"] = cli(folder)
    report["comparisons"]["process"] = exact(reference, arrays(folder, design))
    times = stamps(folder)
    mixed = copy.deepcopy(design)
    for part in mixed["parts"]:
        part.update(volume=.15, pan=.3)
    write_design(folder, mixed)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    assert stamps(folder) == times
    assert json.loads(cache.read_text()) == hashes
    exact({n: a for n, a in reference.items() if n != "mix"}, {n: a for n, a in arrays(folder, design).items() if n != "mix"})
    report["mix_only_reuses_stems"] = True
    inserted = copy.deepcopy(design)
    inserted["parts"].insert(0, {"name": "extra", "instrument": "square", "bars": [f"C4:{compiled['beats_per_bar']}"],
                                "mute": True})
    write_design(folder, inserted)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["unrelated_part"] = exact(reference, arrays(folder, design))
    before = copy.deepcopy(design)
    before.pop("variation")
    write_design(folder / "before", before)
    report["before_cli"] = cli(folder / "before")
    before_audio = arrays(folder / "before", before)
    snapshot(folder / "before")
    for name in reference.keys() - {"mix"} - set(compiled["variation_parts"]):
        assert np.array_equal(reference[name], before_audio[name]), name
    report["before_basis"] = "同じ素材・全パートでvariationのみ除去。新機能以前の別パターンではない。"
    report["before_after_wavs"] = [str(folder / "before" / f"{design['id']}.wav"), str(folder / f"{design['id']}.wav")]
    minor = copy.deepcopy(design)
    minor["key"] = "C minor"
    write_design(folder / "minor", minor)
    cli(folder / "minor")
    _, minor_compiled = snapshot(folder / "minor")
    minor_audio = arrays(folder / "minor", minor)
    assert compiled["notes"]["melody"][0][1] == [64]
    assert minor_compiled["notes"]["melody"][0][1] == [63]
    for name in ("absolute", "held", "drums"):
        assert np.array_equal(reference[name], minor_audio[name]), name
    report["minor_loops"] = {name: seam(audio) for name, audio in minor_audio.items()}
    write_design(folder, design)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    snapshot(folder)
    exact(reference, arrays(folder, design))
    return report


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    assert Path(render.__file__).resolve().parent == ROOT / "bgm"
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "checkout": str(ROOT), "imported_bgm": str(Path(render.__file__).resolve()), "meters": {}}
    design = json.loads((ROOT / "songs/phase1_variations/song.json").read_text(encoding="utf-8"))
    for meter in ("4/4", "3/4", "6/8"):
        report["meters"][meter] = verify_design(output / meter.replace("/", "-"), variant(design, meter))
    report["regression_command"] = run([sys.executable, "-X", "utf8", str(ROOT / "Tests/verify_arrangements_render.py"),
                                        "--output", str(output / "arrangements")], output / "arrangements.log")
    report["unverified"] = ["主観試聴・音楽的自然さ", "実サンプルride/bongo WAV", "3テンプレート・phase1試聴"]
    report["success"] = True
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"変化統合の最終回帰 OK: {output / 'verification.json'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.output.resolve())
