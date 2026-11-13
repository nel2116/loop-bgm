"""stems 段階: パートごとの音を作る（part_hash によるキャッシュ付き）。

返す音はループに折り返した後、音量・定位の前。docs/design/phase2-pipeline.md の 1 節。
"""

import json
import time

import soundfile as sf

from . import render


def render_stems(folder, song, *, force=False, log=print):
    stems_dir = folder / "stems"
    stems_dir.mkdir(exist_ok=True)
    cache_f = stems_dir / "cache.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    new_cache = {}
    stems = {}
    names_now = {p["name"] for p in song["parts"]}
    for old in stems_dir.glob("*.wav"):
        if old.stem not in names_now:
            old.unlink()
    for part in song["parts"]:
        h = render.part_hash(part, song)
        f = stems_dir / f"{part['name']}.wav"
        if not force and cache.get(part["name"]) == h and f.exists():
            stems[part["name"]] = sf.read(f, dtype="float32", always_2d=True)[0]
            log(f"  {part['name']:<14} 変更なし（前の音を使う）")
        else:
            t = time.time()
            audio = render.render_part(part, song)
            render._write_stem(f, audio)
            stems[part["name"]] = audio
            log(f"  {part['name']:<14} 作り直し {time.time() - t:.1f}s")
        new_cache[part["name"]] = h
    cache_f.write_text(json.dumps(new_cache, indent=1), encoding="utf-8")
    return stems
