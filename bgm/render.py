"""Song file -> per-part stems -> loop-ready mix."""

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ENGINE_VERSION
from .instruments import PERCUSSION, SAMPLED, SYNTH_DRUMS, SYNTH_PITCHED
from .paths import SONGS, SR
from .theory import midi_to_hz, parse_pitches

MIX_ONLY_KEYS = {"volume", "pan", "mute", "solo", "note"}
REVERBS = {"none": None, "room": (0.9, 0.012, 7000), "hall": (2.2, 0.025, 5500), "plate": (1.5, 0.005, 9000)}


class SongError(Exception):
    pass


# ---------------------------------------------------------------- loading

def song_dir(ref: str) -> Path:
    p = Path(ref)
    if p.suffix == ".json":
        return p.resolve().parent
    if p.is_dir():
        return p.resolve()
    return (SONGS / ref).resolve()


def load_song(ref: str):
    d = song_dir(ref)
    f = d / "song.json"
    if not f.exists():
        raise SongError(f"曲ファイルがありません: {f}")
    try:
        song = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SongError(f"song.json の書式エラー: {e}") from e
    if not isinstance(song, dict):
        raise SongError(f"song.json の中身は {{\"tempo\": ..., \"bars\": ..., \"parts\": [...]}} の形の"
                        f"オブジェクトにしてください（いまは{_kind(song)}です）")
    song.setdefault("id", d.name)
    if not isinstance(song["id"], str) or not song["id"]:
        raise SongError(f"song.json の id は空でない文字列にしてください（いまは{_kind(song['id'])}です）")
    song.setdefault("beats_per_bar", 4)
    song.setdefault("swing", 0)
    song.setdefault("swing_unit", 0.5)
    song.setdefault("loop", True)
    song.setdefault("master", {})
    if not isinstance(song["master"], dict):
        raise SongError(f"song.json の master は {{\"reverb\": \"room\"}} の形のオブジェクトにしてください"
                        f"（いまは{_kind(song['master'])}です）")
    song["master"].setdefault("reverb", "room")
    song["master"].setdefault("gain_db", 0)
    for k in ("tempo", "bars", "parts"):
        if k not in song:
            raise SongError(f"song.json に {k} がありません")
    if not isinstance(song["parts"], list):
        raise SongError(f"song.json の parts はパートの配列 [...] にしてください（いまは{_kind(song['parts'])}です）")
    for i, part in enumerate(song["parts"]):
        if not isinstance(part, dict):
            raise SongError(f"parts の {i + 1}番目のパートは {{\"name\": ..., \"bars\": [...]}} の形の"
                            f"オブジェクトにしてください（いまは{_kind(part)}です）")
        name = part.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise SongError(f"parts の {i + 1}番目のパートの name は空でない文字列にしてください（いまは{_kind(name)}です）")
    names = [p.get("name") for p in song["parts"]]
    if None in names or len(set(names)) != len(names):
        raise SongError("各パートに重複しない name が必要です")
    _validate_song(song)
    return d, song


def _kind(value):
    """Describe a JSON value's type in Japanese for error messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "真偽値"
    if isinstance(value, (int, float)):
        return "数値"
    if isinstance(value, str):
        return "文字列" if value else "空の文字列"
    if isinstance(value, list):
        return "配列"
    return "オブジェクト"


def _number(value, location, *, positive=False, nonnegative=False, integer=False, float32=False):
    # bool は int の派生だが、曲の数値としては受け付けない。
    valid = type(value) in (int, float)
    try:
        valid = valid and math.isfinite(value)
    except OverflowError:
        valid = False
    valid = valid and (not integer or type(value) is int)
    valid = valid and (not positive or value > 0) and (not nonnegative or value >= 0)
    valid = valid and (not float32 or abs(value) <= np.finfo(np.float32).max)
    if not valid:
        requirement = "正の整数" if integer and positive else "正の有限数" if positive else "0以上の有限数" if nonnegative else "有限数"
        raise SongError(f"{location} は{requirement}にしてください（いまは{_kind(value)}です）")


def _validate_song(song):
    _number(song["tempo"], "song.json の tempo", positive=True)
    _number(song["bars"], "song.json の bars", positive=True, integer=True)
    _number(song["beats_per_bar"], "song.json の beats_per_bar", positive=True)
    _number(song["swing"], "song.json の swing")
    _number(song["swing_unit"], "song.json の swing_unit", positive=True)
    _number(song["master"]["gain_db"], "song.json の master.gain_db")
    if song["master"]["reverb"] is not None and not isinstance(song["master"]["reverb"], str):
        raise SongError("song.json の master.reverb は文字列または null にしてください")
    if song["loop"] is not None and type(song["loop"]) is not bool:
        raise SongError("song.json の loop は真偽値または null にしてください")
    # 小さすぎる長さは丸めで0サンプルになり、fold_loop等で失敗する。
    try:
        seconds = song_seconds(song)
    except OverflowError as e:
        raise SongError("song.json の tempo / bars / beats_per_bar: 曲の長さが大きすぎます") from e
    if not math.isfinite(seconds) or not math.isfinite(seconds * SR) or round(seconds * SR) < 1:
        raise SongError("song.json の tempo / bars / beats_per_bar: 曲の長さを有限の1サンプル以上にしてください")
    sec_per_beat = 60.0 / song["tempo"]
    if not math.isfinite(sec_per_beat):
        raise SongError("song.json の tempo: 1拍の秒数を有限数にしてください")
    if song["swing"]:
        unit = song["swing_unit"]
        beats = song["bars"] * song["beats_per_bar"]
        try:
            offset = song["swing"] * unit / 3
            finite = math.isfinite(beats / unit) and math.isfinite((beats + abs(offset)) * sec_per_beat * SR)
        except OverflowError as e:
            raise SongError("song.json の swing / swing_unit: 拍の位置の計算が大きすぎます") from e
        if not finite:
            raise SongError("song.json の swing / swing_unit: 拍の位置を有限数で計算できる範囲にしてください")
    if not song["parts"]:
        raise SongError("song.json の parts には1つ以上のパートが必要です")
    for part in song["parts"]:
        where = f"[{part['name']}]"
        if part.get("type") is not None and not isinstance(part["type"], str):
            raise SongError(f"{where} type は文字列または null にしてください")
        for key in ("mute", "solo"):
            if part.get(key) is not None and type(part[key]) is not bool:
                raise SongError(f"{where} {key} は真偽値または null にしてください")
        for key in ("volume", "pan", "velocity", "humanize", "reverb"):
            if key in part:
                _number(part[key], f"{where} {key}", nonnegative=key == "humanize", float32=True)
        segs = part.get("bars")
        # 省略、null、空文字列は従来どおり無音。空配列もそのまま使う。
        if segs is not None and segs != "" and not isinstance(segs, list):
            raise SongError(f"{where} bars は小節の配列 [...] または null にしてください")
        if part.get("type") == "drums":
            _validate_drums(part)
        else:
            inst = part.get("instrument")
            if not isinstance(inst, str) or inst not in SAMPLED and inst not in SYNTH_PITCHED:
                raise SongError(f"{where} instrument に存在する楽器名が必要です")
            for key in ("gate", "strum", "transpose", "octave"):
                if key in part:
                    _number(part[key], f"{where} {key}", float32=True)
            for i, seg in enumerate(segs or []):
                if not isinstance(seg, str):
                    raise SongError(f"{where} {i + 1}番目の小節: bars の各要素は音符を並べた文字列にしてください")
            for beat, _, dur, _ in parse_note_bars(part, song):
                if not math.isfinite(dur * sec_per_beat * part.get("gate", 1) * SR):
                    bar = int(beat / song["beats_per_bar"]) + 1
                    raise SongError(f"{where} {bar}番目の小節: 音の長さを有限数で計算できる範囲にしてください（tempo / gate）")


def _validate_drums(part):
    where = f"[{part['name']}]"
    voices = part.get("voices", {})
    if not isinstance(voices, dict):
        raise SongError(f"{where} voices は打楽器名と設定のオブジェクトにしてください")
    for voice, config in voices.items():
        if config is None:
            continue  # 従来の「個別設定なし」を維持する。
        if not isinstance(config, dict):
            raise SongError(f"{where} voices.{voice} は設定のオブジェクトまたは null にしてください")
        for key in ("pan", "volume"):
            if key in config:
                _number(config[key], f"{where} voices.{voice}.{key}", float32=True)
    for i, seg in enumerate(part.get("bars") or []):
        location = f"{where} {i + 1}番目の小節"
        if not isinstance(seg, dict):
            raise SongError(f"{location}: drums の各小節は {{\"kick\": \"x...\"}} の形にしてください")
        for voice, pattern in seg.items():
            if not isinstance(pattern, str):
                raise SongError(f"{location} {voice}: パターンは文字列にしてください")
            if any(ch in "xXo" for ch in pattern) and voice not in PERCUSSION and voice not in SYNTH_DRUMS:
                raise SongError(f"{location}: 打楽器 {voice!r} はありません")
            for ch in pattern.replace(" ", "").replace("|", ""):
                if ch not in "xXo.-_":
                    raise SongError(f"{location} {voice}: 「{ch}」は使えません（x 普通, X 強く, o 弱く, . 休み）")


# ---------------------------------------------------------------- parsing

_TOKEN = re.compile(r"^(?P<p>[^:]+):(?P<d>[0-9./]+)(?:@(?P<v>\d+))?$")


def _num(s):
    return float(Fraction(s))


def parse_note_bars(part, song):
    """Return list of (beat, [midi...], dur_beats, vel) for a note part."""
    bpb = song["beats_per_bar"]
    total_bars = song["bars"]
    segs = part.get("bars") or []
    if not segs:
        return []
    base_vel = part.get("velocity", 90)
    shift = part.get("transpose", 0) + 12 * part.get("octave", 0)
    # parse each segment once
    parsed = []
    for si, seg in enumerate(segs):
        events = []
        pos = 0.0
        if seg.strip() in ("", "-"):
            seg = f"r:{bpb}"
        for tok in seg.split():
            m = _TOKEN.match(tok)
            if not m:
                raise SongError(f"[{part['name']}] {si + 1}番目の小節: 「{tok}」が読めません（例: C4:1  C4+E4+G4:2@80  r:0.5）")
            location = f"[{part['name']}] {si + 1}番目の小節"
            try:
                dur = _num(m.group("d"))
            except (ValueError, ZeroDivisionError, OverflowError) as e:
                raise SongError(f"{location}: 「{tok}」の長さを正の有限数にしてください") from e
            if not math.isfinite(dur) or dur <= 0:
                raise SongError(f"{location}: 「{tok}」の長さを正の有限数にしてください")
            p = m.group("p")
            if p not in ("r", "R"):
                try:
                    pitches = [x + shift for x in parse_pitches(p)]
                    for pitch in pitches:
                        hz = midi_to_hz(pitch)
                        if not math.isfinite(hz) or hz <= 0:
                            raise ValueError("音高を計算できる範囲にしてください")
                except (ValueError, OverflowError) as e:
                    raise SongError(f"[{part['name']}] {si + 1}番目の小節: {e}") from e
                try:
                    vel = int(m.group("v")) if m.group("v") else base_vel
                except ValueError as e:
                    raise SongError(f"{location}: velocity が大きすぎます") from e
                _number(vel, f"{location}: velocity", float32=True)
                events.append((pos, pitches, dur, vel))
            pos += dur
        n_bars = pos / bpb
        if not math.isfinite(n_bars):
            raise SongError(f"[{part['name']}] {si + 1}番目の小節: 長さの合計を有限数にしてください")
        if abs(n_bars - round(n_bars)) > 1e-6 or round(n_bars) == 0:
            raise SongError(f"[{part['name']}] {si + 1}番目の小節: 長さの合計が {pos:g} 拍。"
                            f"1小節 {bpb} 拍の倍数にしてください")
        parsed.append((events, int(round(n_bars))))
    # lay segments end to end, cycling until the song is full
    out = []
    bar = 0
    i = 0
    while bar < total_bars:
        events, nb = parsed[i % len(parsed)]
        for pos, pitches, dur, vel in events:
            beat = bar * bpb + pos
            if beat < total_bars * bpb:
                out.append((beat, pitches, dur, vel))
        bar += nb
        i += 1
    return out


def parse_drum_bars(part, song):
    bpb = song["beats_per_bar"]
    segs = part.get("bars") or []
    base_vel = part.get("velocity", 95)
    out = []
    if not segs:
        return out
    for bar in range(song["bars"]):
        seg = segs[bar % len(segs)]
        if not isinstance(seg, dict):
            raise SongError(f"[{part['name']}] drums の各小節は {{\"kick\": \"x...\"}} の形にしてください")
        for voice, pat in seg.items():
            pat = pat.replace(" ", "").replace("|", "")
            if not pat:
                continue
            step = bpb / len(pat)
            for k, ch in enumerate(pat):
                if ch in ".-_":
                    continue
                vel = {"x": base_vel, "X": min(127, base_vel + 25), "o": max(1, base_vel - 40)}.get(ch)
                if vel is None:
                    raise SongError(f"[{part['name']}] {voice}: 「{ch}」は使えません（x 普通, X 強く, o 弱く, . 休み）")
                out.append((bar * bpb + k * step, voice, vel))
    return out


# ---------------------------------------------------------------- instruments

_inst_cache = {}


def get_instrument(name):
    if name in _inst_cache:
        return _inst_cache[name]
    if name in SAMPLED:
        from .sampler import SampledInstrument
        inst = SampledInstrument(name)
        fn = inst.render
    elif name in SYNTH_PITCHED:
        from .synth import render_pitched
        fn = lambda m, v, d, _k=name: render_pitched(_k, m, v, d)  # noqa: E731
    else:
        raise SongError(f"楽器 {name!r} はありません。`bgm instruments` で一覧を見られます")
    _inst_cache[name] = fn
    return fn


def get_drum(name):
    key = "drum:" + name
    if key in _inst_cache:
        return _inst_cache[key]
    if name in PERCUSSION:
        from .sampler import PercussionVoice
        fn = PercussionVoice(name).render
    elif name in SYNTH_DRUMS:
        from .synth import render_drum
        fn = lambda v, _k=name: render_drum(_k, v)  # noqa: E731
    else:
        raise SongError(f"打楽器 {name!r} はありません。`bgm instruments` で一覧を見られます")
    _inst_cache[key] = fn
    return fn


# ---------------------------------------------------------------- dsp helpers

def fftconvolve(a, b):
    n = len(a) + len(b) - 1
    nfft = 1 << (n - 1).bit_length()
    A = np.fft.rfft(a, nfft, axis=0)
    B = np.fft.rfft(b, nfft, axis=0)
    return np.fft.irfft(A * B, nfft, axis=0)[:n].astype(np.float32)


_ir_cache = {}


def reverb_ir(kind):
    if kind in _ir_cache:
        return _ir_cache[kind]
    spec = REVERBS.get(kind)
    if spec is None:
        _ir_cache[kind] = None
        return None
    rt60, predelay, damp = spec
    n = int((rt60 * 1.2 + predelay) * SR)
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=np.float32) / SR
    env = np.exp(-6.9 * t / rt60)
    pd = int(predelay * SR)
    env[:pd] = 0
    ir = rng.standard_normal((n, 2)).astype(np.float32) * env[:, None]
    # darker tail: low-pass harder as time goes on (approximate with two bands)
    X = np.fft.rfft(ir, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= (1 / (1 + (f / damp) ** 2))[:, None]
    X[f < 120] *= 0.3
    ir = np.fft.irfft(X, n, axis=0).astype(np.float32)
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-9
    ir *= 0.5
    _ir_cache[kind] = ir
    return ir


def place(buf, audio, start):
    if start < 0:
        audio = audio[-start:]
        start = 0
    end = start + len(audio)
    if end > len(buf):
        buf = np.concatenate([buf, np.zeros((end - len(buf) + SR, 2), np.float32)])
    buf[start:end] += audio
    return buf


def fold_loop(x, n):
    """Wrap everything that rings past the loop end back onto the start."""
    out = np.zeros((n, x.shape[1]), np.float32)
    for k in range(0, len(x), n):
        chunk = x[k:k + n]
        out[:len(chunk)] += chunk
    return out


def pan_gains(pan):
    pan = max(-1.0, min(1.0, float(pan)))
    a = (pan + 1) * np.pi / 4
    return np.float32(np.cos(a) * np.sqrt(2)), np.float32(np.sin(a) * np.sqrt(2))


# ---------------------------------------------------------------- render

def song_seconds(song):
    return song["bars"] * song["beats_per_bar"] * 60.0 / song["tempo"]


def _swing(beat, song):
    s = song.get("swing", 0)
    if not s:
        return beat
    u = song.get("swing_unit", 0.5)
    q = beat / u
    if abs(q - round(q)) < 1e-6 and int(round(q)) % 2 == 1:
        return beat + s * u / 3
    return beat


def part_hash(part, song):
    key = {k: v for k, v in part.items() if k not in MIX_ONLY_KEYS}
    ctx = {k: song.get(k) for k in ("tempo", "bars", "beats_per_bar", "swing", "swing_unit", "loop")}
    ctx["reverb"] = song["master"]["reverb"]
    ctx["engine"] = ENGINE_VERSION
    blob = json.dumps([key, ctx], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def render_part(part, song):
    sec_per_beat = 60.0 / song["tempo"]
    n_loop = int(round(song_seconds(song) * SR))
    buf = np.zeros((n_loop + SR * 2, 2), np.float32)
    rng = np.random.default_rng(int(hashlib.md5(part["name"].encode()).hexdigest()[:8], 16))
    hum = float(part.get("humanize", 0.2))

    def jitter_t():
        return rng.normal(0, 0.004 * hum) if hum else 0.0

    def jitter_v(v):
        return int(np.clip(v + (rng.normal(0, 5 * hum) if hum else 0), 1, 127))

    if part.get("type") == "drums":
        for beat, voice, vel in parse_drum_bars(part, song):
            fn = get_drum(voice)
            t = _swing(beat, song) * sec_per_beat + jitter_t()
            audio = fn(jitter_v(vel))
            vp = part.get("voices", {}).get(voice, {})
            if vp:
                gl, gr = pan_gains(vp.get("pan", 0))
                audio = audio * np.array([gl, gr], np.float32) * np.float32(vp.get("volume", 1.0))
            buf = place(buf, audio, int(t * SR))
    else:
        fn = get_instrument(part["instrument"])
        gate = float(part.get("gate", 1.0))
        strum = float(part.get("strum", 0))  # seconds between chord notes
        for beat, pitches, dur, vel in parse_note_bars(part, song):
            t0 = _swing(beat, song) * sec_per_beat + jitter_t()
            dur_s = max(0.02, dur * sec_per_beat * gate)
            v = jitter_v(vel)
            for k, m in enumerate(pitches):
                audio = fn(m, v, dur_s)
                buf = place(buf, audio, int((t0 + k * strum) * SR))
    send = float(part.get("reverb", 0.2))
    ir = reverb_ir(song["master"]["reverb"])
    if ir is not None and send > 0:
        wet = fftconvolve(buf, ir)
        dry = np.zeros_like(wet)
        dry[:len(buf)] = buf
        buf = dry + wet * np.float32(send)
    if song["loop"]:
        if len(buf) > n_loop * 3:
            raise SongError(f"[{part['name']}] 余韻が曲の長さを超えています")
        return fold_loop(buf, n_loop)
    # one-shot: trim trailing silence
    mono = np.abs(buf).max(axis=1)
    peak = mono.max() if len(mono) else 0
    if peak > 0:
        last = len(mono) - np.argmax(mono[::-1] > peak * 0.001)
        buf = buf[:max(last, n_loop)]
    return buf


def check_loop(x):
    """Return (ok, message) about the loop seam of a stereo float array."""
    if len(x) < SR:
        return True, "短いので判定しません"
    d = np.abs(np.diff(x, axis=0))
    typical = np.percentile(d, 99.9) + 1e-6
    jump = np.abs(x[0] - x[-1]).max()
    w = int(0.25 * SR)
    rms_end = np.sqrt((x[-w:] ** 2).mean()) + 1e-9
    rms_start = np.sqrt((x[:w] ** 2).mean()) + 1e-9
    db = 20 * np.log10(rms_start / rms_end)
    msgs = []
    ok = True
    if jump > typical * 1.5:
        ok = False
        msgs.append(f"つなぎ目で波形が跳んでいます（{jump:.3f}、普段の最大 {typical:.3f}）")
    if abs(db) > 9:
        ok = False
        msgs.append(f"終わりと始まりの音量差が {db:+.1f} dB あります")
    if ok:
        msgs.append(f"つなぎ目 OK（段差 {jump:.4f}、音量差 {db:+.1f} dB）")
    return ok, " / ".join(msgs)


def render_song(ref, force=False, mp3=True, log=print):
    d, song = load_song(ref)
    stems_dir = d / "stems"
    stems_dir.mkdir(exist_ok=True)
    cache_f = stems_dir / "cache.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    new_cache = {}
    stems = {}
    names_now = {p["name"] for p in song["parts"]}
    for old in stems_dir.glob("*.wav"):
        if old.stem not in names_now:
            old.unlink()
    t_all = time.time()
    for part in song["parts"]:
        h = part_hash(part, song)
        f = stems_dir / f"{part['name']}.wav"
        if not force and cache.get(part["name"]) == h and f.exists():
            stems[part["name"]] = sf.read(f, dtype="float32", always_2d=True)[0]
            log(f"  {part['name']:<14} 変更なし（前の音を使う）")
        else:
            t = time.time()
            audio = render_part(part, song)
            sf.write(f, audio, SR, subtype="FLOAT")
            stems[part["name"]] = audio
            log(f"  {part['name']:<14} 作り直し {time.time() - t:.1f}s")
        new_cache[part["name"]] = h
    cache_f.write_text(json.dumps(new_cache, indent=1), encoding="utf-8")

    # mix
    n = max(len(a) for a in stems.values())
    mix = np.zeros((n, 2), np.float32)
    solo = [p for p in song["parts"] if p.get("solo")]
    for part in song["parts"]:
        if part.get("mute") or (solo and not part.get("solo")):
            continue
        a = stems[part["name"]]
        gl, gr = pan_gains(part.get("pan", 0))
        mix[:len(a)] += a * (np.array([gl, gr], np.float32) * np.float32(part.get("volume", 0.8)))
    peak = np.abs(mix).max()
    target = 10 ** (-1 / 20) * 10 ** (min(0, song["master"]["gain_db"]) / 20)
    gain = target / peak if peak > 0 else 1.0
    mix *= np.float32(gain)
    if not song["loop"]:
        fade = min(len(mix), int(0.05 * SR))
        mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    (d / "mix.json").write_text(json.dumps({"gain": float(gain), "seconds": n / SR}, indent=1), encoding="utf-8")

    # keep the previous version for before/after comparison
    out_wav = d / f"{song['id']}.wav"
    if out_wav.exists():
        hist = d / "history"
        hist.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(out_wav.stat().st_mtime))
        shutil.copy2(out_wav, hist / f"{stamp}.wav")
        prev_song = d / "last_song.json"
        if prev_song.exists():
            shutil.copy2(prev_song, hist / f"{stamp}.json")
        olds = sorted(hist.glob("*.wav"))
        for o in olds[:-10]:
            o.unlink()
            o.with_suffix(".json").unlink(missing_ok=True)
    sf.write(out_wav, mix, SR, subtype="PCM_16")
    shutil.copy2(d / "song.json", d / "last_song.json")
    if mp3:
        mp3_path = out_wav.with_suffix(".mp3")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_wav), "-codec:a", "libmp3lame",
                            "-b:a", "192k", str(mp3_path)], capture_output=True, text=True)
        if r.returncode != 0:
            log("  mp3 の書き出しに失敗: " + r.stderr.strip()[:200])
    log(f"書き出し: {out_wav}（{n / SR:.1f}秒, {time.time() - t_all:.1f}s）")
    if song["loop"]:
        ok, msg = check_loop(mix)
        log(("  " if ok else "  注意: ") + msg)
    return out_wav
