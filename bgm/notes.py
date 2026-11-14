"""notes 段階: 描画に渡すのと同じ音符列を build/notes.json の形にする。

形式は docs/design/phase2-pipeline.md の 3 節のとおり。揺らぎ (humanize)・strum・区間の切り詰めの前の値を書く。
"""

import json
import math

from . import arrangement
from .render import _is_drums, _swing, compile_song, parse_drum_bars, parse_note_bars, song_seconds

VERSION = 1


def _r(value):
    return round(float(value), 6) + 0.0  # -0.0 を 0.0 にそろえる


def _int(value):
    return int(value) if float(value).is_integer() else _r(value)


def _position(time, song):
    bpb = song["beats_per_bar"]
    bar = math.floor(time / bpb + 1e-9)
    return {"bar": bar + 1, "beat": _r(max(0.0, time - bar * bpb)), "time": _r(time),
            "seconds": _r(_swing(time, song) * 60.0 / song["tempo"])}


def build_notes(song):
    arranged = compile_song(song) if arrangement.enabled(song) or "variation" in song else None
    if arranged is not None and "effective_parts" not in arranged:
        arranged = None
    parts = []
    for part in song["parts"]:
        name = part["name"]
        role = part.get("role")
        varied = arranged is not None and name in arranged.get("variation_parts", [])
        if arranged is not None:
            part = arranged["effective_parts"][name]
        events = []
        if _is_drums(part):
            source = arranged["rhythm"][name] if varied else parse_drum_bars(part, song)
            for beat, voice, vel in source:
                events.append({**_position(beat, song), "midi": None, "drum": voice, "duration": None,
                               "velocity": _int(vel), "instrument": voice})
            parts.append({"name": name, "role": role, "type": "drums", "instrument": None, "events": events})
            continue
        source = arranged["notes"][name] if arranged is not None else parse_note_bars(part, song)
        metadata = arranged["event_metadata"].get(name) if varied else None
        for index, (beat, pitches, dur, vel) in enumerate(source):
            voice = metadata[index]["instrument"] if metadata is not None else part["instrument"]
            for midi in pitches:
                events.append({**_position(beat, song), "midi": _int(midi), "drum": None, "duration": _r(dur),
                               "velocity": _int(vel), "instrument": voice})
        parts.append({"name": name, "role": role, "type": "notes", "instrument": part.get("instrument"),
                      "events": events})
    return {"song": song["id"], "version": VERSION, "tempo": song["tempo"], "beats_per_bar": song["beats_per_bar"],
            "bars": song["bars"], "seconds": _r(song_seconds(song)), "loop": bool(song["loop"]), "parts": parts}


def write_notes(folder, doc):
    build = folder / "build"
    build.mkdir(exist_ok=True)
    path = build / "notes.json"
    path.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return path
