"""#75 の書き出しの段階分けで、songs/ の全曲のマスターが変わらないことを確かめる。

各曲を、段階分けの前のコミット（BASELINE）の bgm と、いまの bgm で書き出し、
旧 songs/<id>/<id>.wav と新 out/<id>.wav のサンプルを比べる。録音音源（samples/）を使う曲も含むので CI では動かさない。

    python -X utf8 Tests/verify_phase2_pipeline.py --output %TEMP%/loopbgm75/verify
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "34b884c"  # develop: #74（度数の見本曲の form を A B に）のマージ。段階分けの直前。

OLD_RENDER = ("import sys; from bgm.render import render_song; "
              "render_song(sys.argv[1], force=True, mp3=False, log=lambda *_: None)")


def _render(folder, cwd):
    process = subprocess.run([sys.executable, "-X", "utf8", "-c", OLD_RENDER, str(folder)], cwd=cwd,
                             capture_output=True, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(process.stderr.strip().splitlines()[-1] if process.stderr.strip() else "失敗")


def _copy_design(song_id, folder):
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "songs" / song_id / "song.json", folder / "song.json")


def verify(output, baseline=BASELINE):
    output.mkdir(parents=True, exist_ok=True)
    report = {"baseline": baseline,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "songs": {}}
    archive = subprocess.check_output(["git", "archive", "--format=zip", baseline, "bgm"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="loopbgm-phase2-") as scratch:
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            package.extractall(scratch)
        # 古い bgm も同じ samples/ を読むように、取り出した paths.py の音源の場所だけを差し替える。
        paths = Path(scratch) / "bgm" / "paths.py"
        text = paths.read_text(encoding="utf-8")
        assert 'SAMPLES = ROOT / "samples"' in text
        paths.write_text(text.replace('SAMPLES = ROOT / "samples"', f"SAMPLES = Path({str(ROOT / 'samples')!r})"),
                         encoding="utf-8")
        for song_file in sorted((ROOT / "songs").glob("*/song.json")):
            song_id = song_file.parent.name
            entry = report["songs"][song_id] = {}
            old_folder, new_folder = output / "old" / song_id, output / "new" / song_id
            for folder in (old_folder, new_folder):
                shutil.rmtree(folder, ignore_errors=True)
                _copy_design(song_id, folder)
            try:
                _render(old_folder, scratch)
                _render(new_folder, ROOT)
            except RuntimeError as e:
                entry.update(equal=None, error=str(e))
                continue
            design = json.loads(song_file.read_text(encoding="utf-8"))
            master_id = design.get("id", song_id)
            old, sr_old = sf.read(old_folder / f"{master_id}.wav", dtype="int16")
            new, sr_new = sf.read(new_folder / "out" / f"{master_id}.wav", dtype="int16")
            entry.update(equal=bool(sr_old == sr_new and old.shape == new.shape and np.array_equal(old, new)),
                         frames=len(new), report=(new_folder / "out" / "report.json").exists(),
                         notes=(new_folder / "build" / "notes.json").exists())
    report["success"] = all(e.get("equal") for e in report["songs"].values())
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", default=BASELINE)
    args = parser.parse_args()
    report = verify(args.output, args.baseline)
    for song_id, entry in report["songs"].items():
        state = "同じ" if entry.get("equal") else ("比べられない: " + entry["error"] if "error" in entry else "違う")
        print(f"{song_id}: {state}")
    print(("段階分け検証 OK: " if report["success"] else "段階分け検証 NG: ") + str(args.output / "verification.json"))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
