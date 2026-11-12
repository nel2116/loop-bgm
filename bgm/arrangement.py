"""装飾APIの統合と、タプルを変えない境界・原イベント情報。"""

from .arrange_accents import compile_offbeat_tick, compile_phrase_start
from .arrange_copy import compile_copy, reference_order, resolve_copy_instrument
from .arrange_response import compile_counter
from .instruments import PERCUSSION, SAMPLED, SYNTH_DRUMS, SYNTH_PITCHED
from .structure import expand_form, meter_to_beats


def enabled(song):
    return any(any(k in p for k in ("copy", "accent", "source")) for p in song["parts"])


def effective_parts(song):
    order = reference_order(song["parts"], reference_fields=("copy", "source"))
    named = {p["name"]: dict(p) for p in song["parts"]}
    instruments = {}
    for name in order:
        part = named[name]
        if "copy" in part:
            part["instrument"] = resolve_copy_instrument(part, instruments)
        if part.get("accent") != "offbeat_tick" and "groove" not in part and part.get("type") != "drums":
            inst = part.get("instrument")
            if not isinstance(inst, str) or inst not in SAMPLED and inst not in SYNTH_PITCHED:
                raise ValueError(f"[{name}] 1番目の小節: instrument に存在する楽器名が必要です")
            instruments[name] = inst
    return named


def _occurrence(beat, occurrences, beats):
    return next(o for o in occurrences if o["start_beat"] <= beat < o["start_beat"] + o["bars"] * beats)


def _selected(part, occurrences):
    selected = part.get("sections")
    if "sections" in part and (not isinstance(selected, list)
                               or any(not isinstance(s, str) or s not in {o["name"] for o in occurrences} for s in selected)):
        raise ValueError(f"[{part['name']}] 1番目の小節: sections は展開された出現名の一覧で指定してください")
    return selected


def _metadata(part, events, compiled, source_events=()):
    occurrences, beats = compiled["occurrences"], compiled["beats_per_bar"]
    end = compiled["bars"] * beats
    duplicates, result = {}, []
    for beat, pitches, duration, velocity in events:
        identity = (beat, tuple(pitches), duration, velocity)
        ordinal = duplicates.get(identity, 0)
        duplicates[identity] = ordinal + 1
        window, tones = None, list(range(len(pitches)))
        if "style" in part or "accent" in part:
            occ = _occurrence(beat, occurrences, beats)
            chord = next(c for c in reversed(compiled["harmony"]) if c["beat"] <= beat)
            left = max(chord["beat"], occ["start_beat"])
            right = min(chord["beat"] + chord["duration"], occ["start_beat"] + occ["bars"] * beats, end)
            if part.get("accent") == "counter":
                left = max(left, (beat // beats) * beats)
                right = min(right, (beat // beats + 1) * beats)
                for onset, _, held, _ in source_events:
                    if onset + held <= beat:
                        left = max(left, onset + held)
                    elif onset > beat:
                        right = min(right, onset)
            window = [left, right]
            if part.get("role") == "chords" and part.get("style") in ("arpeggio_up", "broken", "strum", "waltz"):
                raw = [p + part.get("octave", 0) * 12 + part.get("transpose", 0) for p in chord["pitches"]]
                low, high = SAMPLED.get(part["instrument"], {}).get("range", (0, 127))
                shift = min(max(0, -((min(raw) - low) // 12)), (high - max(raw)) // 12) * 12
                tones = [[p + shift for p in raw].index(p) for p in pitches]
        result.append({"window": window, "ordinal": ordinal, "tones": tones})
    return result


def compile_arrangements(song, compile_direct):
    """参照を先に検査し、元の設計図と旧タプルを保持して依存順に展開する。"""
    parts = effective_parts(song)
    order = reference_order(song["parts"], reference_fields=("copy", "source"))
    occurrences = expand_form(song)
    for part in parts.values():
        _selected(part, occurrences)
        if ("role" in part and part["role"] not in ("melody", "bass", "chords", "rhythm", "arrange")
                or "type" in part and part["type"] not in ("notes", "drums")):
            raise ValueError(f"[{part['name']}] 1番目の小節: role / type の指定が不正です")
        if "accent" in part and part["accent"] not in ("phrase_start", "offbeat_tick", "counter"):
            raise ValueError(f"[{part['name']}] 1番目の小節: accent は phrase_start / offbeat_tick / counter で指定してください")
    direct = [p for p in parts.values() if not any(k in p for k in ("copy", "accent", "source"))]
    # 空選択でも直接記譜の誤りを隠さない。実際の選択とは独立の検証だけを行う。
    for part in direct:
        if "phrases" in part or "grid" in part:
            compile_direct(dict(song, parts=[{k: v for k, v in part.items() if k != "sections"}]))
    compiled = compile_direct(dict(song, parts=direct))
    metadata = {}
    beats = meter_to_beats(song["meter"])
    for name in order:
        part = parts[name]
        note_range = SAMPLED.get(part.get("instrument"), {}).get("range", (0, 127))
        if "copy" in part:
            source = compiled["notes"][part["copy"]]
            events = compile_copy(part, song, occurrences, source, note_range=note_range)
            compiled["notes"][name] = events
            selected = _selected(part, occurrences)
            kept = [(event, meta) for event, meta in zip(source, metadata[part["copy"]], strict=True)
                    if selected is None or _occurrence(event[0], occurrences, beats)["name"] in selected]
            metadata[name] = []
            for (source_event, meta), _event in zip(kept, events, strict=True):
                occ = _occurrence(source_event[0], occurrences, beats)
                left, right = occ["start_beat"], occ["start_beat"] + occ["bars"] * beats
                if meta["window"] is not None:
                    left, right = max(left, meta["window"][0]), min(right, meta["window"][1])
                metadata[name].append(dict(meta, window=[left, min(right, compiled["bars"] * beats)]))
        elif part.get("accent") == "offbeat_tick":
            compiled["rhythm"][name] = compile_offbeat_tick(part, song, occurrences, available_voices=set(PERCUSSION) | set(SYNTH_DRUMS))
        elif "accent" in part:
            if part["accent"] == "phrase_start":
                events = compile_phrase_start(part, song, occurrences, compiled["harmony"], note_range=note_range)
                source = []
            else:
                source = compiled["notes"][part["source"]]
                events = compile_counter(part, song, occurrences, compiled["harmony"], source, note_range=note_range)
            compiled["notes"][name] = events
            metadata[name] = _metadata(part, events, compiled, source)
        elif name in compiled["notes"]:
            events = compiled["notes"][name]
            metadata[name] = _metadata(part, events, compiled)
            if "phrases" not in part and "grid" not in part and "style" not in part:
                selected = _selected(part, occurrences)
                kept = [(event, meta) for event, meta in zip(events, metadata[name], strict=True)
                        if selected is None or _occurrence(event[0], occurrences, beats)["name"] in selected]
                compiled["notes"][name] = [e for e, _ in kept]
                metadata[name] = [m for _, m in kept]
    compiled.update(effective_parts=parts, event_metadata=metadata)
    return compiled
