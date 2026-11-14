"""report 段階: 測定値とチェック結果を out/report.json（docs/spec.md 6.3 の形）に書く。

契約は docs/design/phase2-pipeline.md の 4 節。時刻やパスは書かない（同じ曲なら同じバイト列）。
"""

import json
import math

from .loudness import integrated_lufs, sample_peak_db
from .paths import SR

VERSION = 1


def _finite(value, digits):
    return round(value, digits) + 0.0 if math.isfinite(value) else None


def measure(master, song, sr=SR):
    return {"lufs": _finite(integrated_lufs(master, sr), 1),
            "peak_db": _finite(sample_peak_db(master), 1),
            "loop_seconds": round(len(master) / sr, 3)}


def build_report(song, metrics, issues):
    return {"song": song["id"], "version": VERSION,
            "passed": not any(i.level == "error" for i in issues),
            "metrics": dict(metrics),
            "issues": [{"level": i.level, "check": i.check, "part": i.part, "bars": sorted(set(i.bars)),
                        "message": i.message, "hint": i.hint} for i in issues]}


def write_report(folder, doc):
    out = folder / "out"
    out.mkdir(exist_ok=True)
    path = out / "report.json"
    path.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return path
