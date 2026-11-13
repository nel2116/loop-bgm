"""Play VSCO 2 CE samples at any pitch."""

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .instruments import PERCUSSION, SAMPLED, vel_rank
from .paths import ROOT, SAMPLES, SR
from .theory import note_to_midi

VSCO = SAMPLES / "vsco2"
CALIB = ROOT / "data" / "calibration.json"


def load_calibration():
    if CALIB.exists():
        return json.loads(CALIB.read_text(encoding="utf-8"))
    return {}


@lru_cache(maxsize=4096)
def load_wav(path: str):
    """Read a sample as float32 stereo, with leading silence trimmed. Returns (data, sr)."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    mono = np.abs(data).max(axis=1)
    peak = mono.max() if len(mono) else 0
    if peak > 0:
        idx = np.argmax(mono > peak * 0.003)
        start = max(0, idx - int(sr * 0.002))
        data = data[start:]
        fade = min(len(data), int(sr * 0.002))
        if fade and start > 0:
            data[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    return np.ascontiguousarray(data), sr


def _chart(folder: Path):
    out = {}
    f = folder / "MappingChart.txt"
    for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^(\d+)=(\d+)", line.strip())
        if m:
            out[int(m.group(1))] = int(m.group(2))
    return out


def _env_release(n_hold, n_rel, total):
    env = np.ones(total, dtype=np.float32)
    if n_hold < total:
        t = np.arange(total - n_hold, dtype=np.float32)
        env[n_hold:] = 10 ** (-3 * t / max(1, n_rel))
    return env


def resample(data, ratio, n_out):
    """Read `data` at speed `ratio` (linear interpolation), producing n_out frames."""
    pos = np.arange(n_out, dtype=np.float64) * ratio
    pos = pos[pos < len(data) - 1]
    i = pos.astype(np.int64)
    frac = (pos - i).astype(np.float32)[:, None]
    out = data[i] * (1 - frac) + data[i + 1] * frac
    return out


class SampledInstrument:
    def __init__(self, name):
        self.name = name
        self.spec = SAMPLED[name]
        cal = load_calibration().get(name, {})
        self.octave_fix = cal.get("oct", 0)
        self.tune = cal.get("tune", 0.0)  # semitones the samples are sharp by
        self.norm = cal.get("norm", 1.0)
        folder = VSCO / self.spec["src"]
        if not folder.exists():
            raise FileNotFoundError(f"音源 {name} がありません。`bgm fetch` を実行してください")
        rx = re.compile(self.spec["rx"])
        idx_map = self.spec.get("idx_map")
        chart = _chart(folder) if idx_map == "chart" else None
        zones = []
        for p in sorted(folder.iterdir()):
            m = rx.match(p.name)
            if not m:
                continue
            g = m.groupdict()
            if g.get("note"):
                root = note_to_midi(g["note"])
            elif chart is not None:
                root = chart[int(g["idx"])]
            else:
                base, step = idx_map
                root = base + int(g["idx"]) * step
            root += 12 * self.octave_fix
            zones.append(dict(root=root, vel=vel_rank(g.get("vel")), rr=int(g.get("rr") or 1), path=str(p)))
        if not zones:
            raise FileNotFoundError(f"音源 {name} のファイルが見つかりません（{folder}）")
        self.zones = zones
        self.roots = sorted({z["root"] for z in zones})
        self._rr = {}

    def pick(self, midi, vel):
        root = min(self.roots, key=lambda r: (abs(r - midi), r > midi))
        cands = [z for z in self.zones if z["root"] == root]
        layers = sorted({z["vel"] for z in cands})
        layer = layers[min(len(layers) - 1, int(vel / 128 * len(layers)))]
        cands = [z for z in cands if z["vel"] == layer]
        k = (root, layer)
        i = self._rr.get(k, 0)
        self._rr[k] = i + 1
        return cands[i % len(cands)]

    def render(self, midi, vel, dur_s):
        z = self.pick(midi, vel)
        data, sr = load_wav(z["path"])
        ratio = 2 ** ((midi - z["root"] - self.tune) / 12) * sr / SR
        rel = self.spec["release"]
        n_out = int((dur_s + rel) * SR)
        out = resample(data, ratio, n_out)
        env = _env_release(int(dur_s * SR), int(rel * SR), len(out))
        amp = self.norm * self.spec["gain"] * (vel / 127) ** 0.8
        return out * (env * amp)[:, None]


class PercussionVoice:
    def __init__(self, name):
        self.name = name
        self.spec = PERCUSSION[name]
        cal = load_calibration().get("perc:" + name, {})
        self.norm = cal.get("norm", 1.0)
        rx = re.compile("^" + self.spec["rx"] + "$")
        # search only the folder that the regex points at
        folder = VSCO / Path(self.spec["rx"].replace("\\.", ".")).parent.as_posix().split("(")[0]
        zones = []
        for p in VSCO.rglob("*.wav") if not folder.exists() else folder.iterdir():
            rel = p.relative_to(VSCO).as_posix()
            m = rx.match(rel)
            if m:
                g = m.groupdict()
                zones.append(dict(vel=vel_rank(g.get("vel")), rr=int(g.get("rr") or 1), path=str(p)))
        if not zones:
            raise FileNotFoundError(f"打楽器 {name} の音源がありません。`bgm fetch` を実行してください")
        self.zones = sorted(zones, key=lambda z: (z["vel"], z["rr"]))
        self.layers = sorted({z["vel"] for z in zones})
        self._rr = 0

    def render(self, vel):
        layer = self.layers[min(len(self.layers) - 1, int(vel / 128 * len(self.layers)))]
        cands = [z for z in self.zones if z["vel"] == layer]
        z = cands[self._rr % len(cands)]
        self._rr += 1
        data, sr = load_wav(z["path"])
        if sr != SR:
            data = resample(data, sr / SR, int(len(data) * SR / sr))
        return data * (self.norm * self.spec["gain"] * (vel / 127) ** 0.8)


def missing_samples(instruments=(), drums=()):
    """音源がそろっていない楽器名と打楽器名を、重複なく名前順に返す。"""
    missing = set()
    for names, voice in ((instruments, SampledInstrument), (drums, PercussionVoice)):
        for name in set(names):
            try:
                voice(name)
            except FileNotFoundError:
                missing.add(name)
    return sorted(missing)
