"""write 段階: 仕上がった音を songs/<id>/out/ へ書き出す。

置き場所は docs/design/phase2-pipeline.md の 2 節。history/ と last_song.json は曲フォルダーに置いたまま。
#75 の MP3 は従来どおり ffmpeg で作る。
"""

import shutil
import subprocess
import time

import soundfile as sf

from .paths import SR

HISTORY_KEEP = 10


def _rotate_history(folder, previous):
    """前回の書き出しを history/<更新時刻>.wav（と設計図 .json）に残し、新しい10件だけ保つ。"""
    hist = folder / "history"
    hist.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(previous.stat().st_mtime))
    shutil.copy2(previous, hist / f"{stamp}.wav")
    prev_song = folder / "last_song.json"
    if prev_song.exists():
        shutil.copy2(prev_song, hist / f"{stamp}.json")
    olds = sorted(hist.glob("*.wav"))
    for o in olds[:-HISTORY_KEEP]:
        o.unlink()
        o.with_suffix(".json").unlink(missing_ok=True)


def _clean_old_layout(folder, song, log):
    """#75 より前の置き場所（曲フォルダー直下）に残った書き出しを消す。"""
    old = [folder / f"{song['id']}.wav", folder / f"{song['id']}.mp3", folder / "mix.json"]
    removed = [p.name for p in old if p.is_file()]
    for name in removed:
        (folder / name).unlink()
    if removed:
        log(f"  古い場所の書き出しを片付けました: {', '.join(removed)}")


def write_outputs(folder, song, master, profile, *, mp3=True, log=print):
    """書き出したファイルを {"wav": Path, "mp3": Path（作れたとき）} で返す。"""
    out = folder / "out"
    out.mkdir(exist_ok=True)
    out_wav = out / f"{song['id']}.wav"
    old_wav = folder / f"{song['id']}.wav"
    previous = out_wav if out_wav.exists() else old_wav if old_wav.is_file() else None
    if previous is not None:
        _rotate_history(folder, previous)
    _clean_old_layout(folder, song, log)
    sf.write(out_wav, master, SR, subtype="PCM_16")
    shutil.copy2(folder / "song.json", folder / "last_song.json")
    written = {"wav": out_wav}
    if mp3:
        mp3_path = out_wav.with_suffix(".mp3")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_wav), "-codec:a", "libmp3lame",
                            "-b:a", "192k", str(mp3_path)], capture_output=True, text=True)
        if r.returncode != 0:
            log("  mp3 の書き出しに失敗: " + r.stderr.strip()[:200])
        else:
            written["mp3"] = mp3_path
    return written
