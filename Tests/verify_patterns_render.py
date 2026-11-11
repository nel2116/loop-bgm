"""追加伴奏型の全配列・旧型・歴史回帰をrepo入力だけで再検証する。"""

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

from bgm import render

if __package__:
    from Tests.verify_accompaniment_render import ROOT, arrays, cli, exact, write_design
else:
    from verify_accompaniment_render import ROOT, arrays, cli, exact, write_design

BASELINE = "cb1c368248075efd93144577da5db8ca7a8fbd8a"


def seam(audio):
    ok, message = render.check_loop(audio)
    w = min(len(audio), round(.25 * render.SR))
    jump = float(np.max(np.abs(audio[0] - audio[-1])))
    typical = float(np.percentile(np.abs(np.diff(audio, axis=0)), 99.9) + 1e-6)
    rms = [float(np.sqrt((edge ** 2).mean()) + 1e-9) for edge in (audio[:w], audio[-w:])]
    return {"ok": bool(ok), "message": message, "samples": len(audio), "jump": jump,
            "typical_99_9": typical, "jump_ratio": jump / typical, "rms_start_end": rms,
            "level_delta_db": float(20 * np.log10(rms[0] / rms[1]))}


def stamps(folder):
    return {p.name: p.stat().st_mtime_ns for p in (folder / "stems").glob("*.wav")}


def check_design(folder, design):
    write_design(folder, design)
    command = cli(folder, folder / "cli.log")
    reference = arrays(folder, design)
    _, song = render.load_song(str(folder))
    compiled = render.compile_song(song)
    (folder / "events.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"command": command, "wav": str(folder / f"{design['id']}.wav"), "comparisons": {},
              "loops": {name: seam(audio) for name, audio in reference.items()}}
    for label in ("force", "force_again"):
        render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
        report["comparisons"][label] = exact(reference, arrays(folder, design))
    other = copy.deepcopy(design)
    other["id"], other["key"] = "unrelated", "D minor"
    # 無関係パートの挿入・順序も対象イベントのseedを動かさない。
    target = copy.deepcopy(design["parts"][1])
    other["parts"].insert(0, dict(target, name="unrelated_part"))
    write_design(folder / "interleaved", other)
    render.render_song(str(folder / "interleaved"), force=True, mp3=False, log=lambda *_: None)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["interleaved"] = exact(reference, arrays(folder, design))
    inserted = copy.deepcopy(design)
    inserted["parts"].insert(0, dict(target, name="unrelated_part"))
    write_design(folder, inserted)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    report["comparisons"]["other_part"] = exact({k: v for k, v in reference.items() if k != "mix"},
                                                              {k: v for k, v in arrays(folder, design).items() if k != "mix"})
    write_design(folder, design)
    render.render_song(str(folder), force=True, mp3=False, log=lambda *_: None)
    cache = folder / "stems/cache.json"
    hashes, times = json.loads(cache.read_text(encoding="utf-8")), stamps(folder)
    partial = dict(hashes)
    for name in ("bass", "rhythm"):
        partial.pop(name)
    cache.write_text(json.dumps(partial), encoding="utf-8")
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    report["comparisons"]["partial_cache"] = exact(reference, arrays(folder, design))
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    assert all(stamps(folder)[name] == stamp for name, stamp in times.items() if name not in ("bass.wav", "rhythm.wav"))
    report["process_command"] = cli(folder, folder / "process-cli.log")
    report["comparisons"]["process"] = exact(reference, arrays(folder, design))
    times = stamps(folder)
    mixed = copy.deepcopy(design)
    for part in mixed["parts"]:
        part.update(volume=.17, pan=.23)
    write_design(folder, mixed)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    assert json.loads(cache.read_text(encoding="utf-8")) == hashes
    assert stamps(folder) == times
    exact({k: v for k, v in reference.items() if k != "mix"}, {k: v for k, v in arrays(folder, design).items() if k != "mix"})
    report["mix_only_hash_mtime_stems_equal"] = True
    write_design(folder, design)
    render.render_song(str(folder), mp3=False, log=lambda *_: None)
    exact(reference, arrays(folder, design))
    minor = copy.deepcopy(design)
    minor["key"] = "C minor"
    write_design(folder / "minor", minor)
    report["minor_command"] = cli(folder / "minor", folder / "minor/cli.log")
    minor_audio = arrays(folder / "minor", minor)
    _, minor_song = render.load_song(str(folder / "minor"))
    minor_compiled = render.compile_song(minor_song)
    (folder / "minor/events.json").write_text(json.dumps(minor_compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    report["minor_wav"] = str(folder / "minor" / f"{design['id']}.wav")
    report["minor_loops"] = {name: seam(audio) for name, audio in minor_audio.items()}
    for name in ("melody", "bass", "chords"):
        assert not np.array_equal(reference[name], minor_audio[name]), name
        assert compiled["notes"][name] != minor_compiled["notes"][name]
    for name in ("absolute", "direct_drums", "rhythm"):
        assert np.array_equal(reference[name], minor_audio[name]), name
    assert not np.array_equal(reference["mix"], minor_audio["mix"])
    assert compiled["notes"]["absolute"] == minor_compiled["notes"]["absolute"]
    assert compiled["rhythm"] == minor_compiled["rhythm"]
    report["key_only"] = {"changed": ["melody", "bass", "chords", "mix"], "equal": ["absolute", "direct_drums", "rhythm"]}
    before = copy.deepcopy(design)
    before["parts"] = [p for p in before["parts"] if "style" not in p and "groove" not in p]
    write_design(folder / "before", before)
    report["before_command"] = cli(folder / "before", folder / "before/cli.log")
    report["before_baseline"] = "新型未実装に対応する生成bass/chords/rhythmなし。同じ旧パートのみ。"
    report["before_wav"] = str(folder / "before" / f"{design['id']}.wav")
    old = arrays(folder / "before", before)
    for name in ("melody", "absolute", "direct_drums"):
        assert np.array_equal(reference[name], old[name])
    report["loops"]["before_mix"] = seam(old["mix"])
    # style/grooveは対象パートだけを失効させる。
    for name, field, value in (("bass", "style", "root_quarter"), ("chords", "style", "block"),
                               ("rhythm", "groove", "ambient_none")):
        changed = copy.deepcopy(song)
        part = next(p for p in changed["parts"] if p["name"] == name)
        part[field] = value
        original_hash = {p["name"]: render.part_hash(p, song) for p in song["parts"]}
        assert [p["name"] for p in changed["parts"] if render.part_hash(p, changed) != original_hash[p["name"]]] == [name]
    report["style_groove_local_invalidation"] = True
    return report


def old_numeric(scratch):
    cases, current = [], []
    for meter in ("4/4", "3/4", "6/8"):
        for role, styles in (("bass", ("root_whole", "root_quarter", "root_fifth")), ("chords", ("pad", "block", "offbeat"))):
            for style in styles:
                for key in ("C major", "C minor"):
                    for selection in (None, ["A"], ["A'"], []):
                        song = {"key": key, "meter": meter, "form": ["A", "B", "A", "A'"],
                                "sections": {"A": {"bars": 1, "chords": "Iadd9/3 ii V"}, "B": {"bars": 1, "chords": "vii° iv"}},
                                "parts": [{"name": "old", "role": role, "style": style, "instrument": "bass", "transpose": 2}]}
                        if selection is not None:
                            song["parts"][0]["sections"] = selection
                        cases.append(song)
                        current.append(render.compile_song(song))
    for meter, grooves in (("4/4", ("8beat", "march", "ambient_none")), ("3/4", ("waltz", "ambient_none")),
                           ("6/8", ("march", "ambient_none"))):
        for groove in grooves:
            song = copy.deepcopy(cases[0])
            song["meter"] = meter
            song["parts"] = [{"name": "old", "role": "rhythm", "groove": groove}]
            cases.append(song)
            current.append(render.compile_song(song))
    payload = scratch / "cases.json"
    payload.write_text(json.dumps(cases), encoding="utf-8")
    code = ("import json,sys; from bgm.render import compile_song; "
            "print(json.dumps([compile_song(s) for s in json.load(open(sys.argv[1]))]))")
    old = json.loads(subprocess.check_output([sys.executable, "-c", code, str(payload)], cwd=scratch, text=True))
    assert old == json.loads(json.dumps(current))
    return {"baseline": BASELINE, "cases": len(cases), "complete_compiled_objects_equal": True}


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "patterns": {}}
    design = json.loads((ROOT / "songs/phase1_patterns/song.json").read_text(encoding="utf-8"))
    variants = [("bass", s, "4/4") for s in ("octave_8th", "walking", "arpeggio")]
    variants += [("chords", s, "3/4" if s == "waltz" else "4/4") for s in ("arpeggio_up", "broken", "strum", "waltz")]
    variants += [("rhythm", s, "4/4") for s in ("16beat", "shuffle", "bossa")]
    for role, pattern, meter in variants:
        variant = copy.deepcopy(design)
        variant["meter"] = meter
        next(p for p in variant["parts"] if p["name"] == role)["groove" if role == "rhythm" else "style"] = pattern
        if meter == "3/4":
            variant["parts"][0]["phrases"] = {"A": "1 3 5", "B": "4 3 2"}
            variant["parts"][3]["groove"] = "waltz"
            variant["parts"][4]["bars"] = ["C5:0.5 r:2.5"]
        report["patterns"][pattern] = check_design(output / pattern, variant)
    archive = subprocess.check_output(["git", "archive", "--format=zip", BASELINE, "bgm"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="loopbgm-patterns-") as temp:
        scratch = Path(temp)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            package.extractall(scratch)
        report["old_numeric"] = old_numeric(scratch)
        # 旧型見本のmixを含めた全配列をbatch3前と比較する。
        old_design = json.loads((ROOT / "songs/phase1_accompaniment/song.json").read_text(encoding="utf-8"))
        write_design(output / "old-before", old_design)
        cli(output / "old-before", output / "old-before/cli.log", cwd=scratch)
        write_design(output / "old-after", old_design)
        cli(output / "old-after", output / "old-after/cli.log")
        report["old_audio"] = exact(arrays(output / "old-before", old_design), arrays(output / "old-after", old_design))
    # 歴史fixtureの例外規則と既存伴奏helperはそのまま実行する。
    report["regression_commands"] = []
    for helper, name in (("verify_phase1_render.py", "phase1"), ("verify_accompaniment_render.py", "accompaniment")):
        command = [sys.executable, "-X", "utf8", str(ROOT / "Tests" / helper), "--output", str(output / name)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)
        (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        report["regression_commands"].append(command)
    report["unverified"] = ["swing_ride/bongo_8beatの実サンプル描画（catalog/打点/実renderer配列位置はpytestで検証）",
                            "主観的試聴", "既に消失した実移譲origin worktreeの削除"]
    report["success"] = True
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"追加型統合検証 OK: {output / 'verification.json'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output.resolve())
