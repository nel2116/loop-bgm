"""書き出しの段階を順に呼ぶ: notes → stems → mix → master → write → check → report。

各段階の入出力は docs/design/phase2-pipeline.md の 1 節。ここは段階をつなぐだけで、処理は各モジュールに置く。
"""

import json
import time

from . import export, mix, notes, profiles, report, stems
from .checks import CheckContext, run_checks
from .checks.audio import measure_seam
from .paths import SR

SEAM_CHECKS = ("seam_click", "seam_level")


def run(folder, song, *, force=False, mp3=True, log=print):
    """曲を書き出して out/<id>.wav のパスを返す。"""
    profile = profiles.resolve(song)
    notes_doc = notes.build_notes(song)
    notes.write_notes(folder, notes_doc)
    t_all = time.time()
    part_audio = stems.render_stems(folder, song, force=force, log=log)
    mixed = mix.mix_stems(song, part_audio, profile)
    master, info = mix.finish(song, mixed, profile)
    build = folder / "build"
    build.mkdir(exist_ok=True)
    (build / "mix.json").write_text(json.dumps({"gain": info["gain"], "seconds": len(master) / SR}, indent=1),
                                    encoding="utf-8")
    written = export.write_outputs(folder, song, master, profile, mp3=mp3, log=log)
    log(f"書き出し: {written['wav']}（{len(master) / SR:.1f}秒, {time.time() - t_all:.1f}s）")
    ctx = CheckContext(song=song, profile=profile, notes=notes_doc, stems=part_audio, master=master, sr=SR)
    issues = run_checks(ctx)
    if song["loop"]:
        seam = measure_seam(master, SR)
        if seam is None:
            log("  短いので判定しません")
        elif not any(i.check in SEAM_CHECKS for i in issues):
            jump, _, db = seam
            log(f"  つなぎ目 OK（段差 {jump:.4f}、音量差 {db:+.1f} dB）")
    for issue in issues:
        log("  注意: " + issue.message)
    report.write_report(folder, report.build_report(song, report.measure(master, song), issues))
    return written["wav"]
