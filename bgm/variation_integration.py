"""承認済み変化APIを既存の音符コンパイラへ接続する。DSPは行わない。"""

from copy import deepcopy

from . import arrangement
from .arrange_accents import compile_phrase_start
from .arrange_copy import compile_copy, reference_order
from .arrange_response import compile_counter
from .bass import compile_bass
from .chords import compile_chords
from .instruments import PERCUSSION, SAMPLED, SYNTH_DRUMS, SYNTH_PITCHED
from .melody import compile_melody
from .structure import expand_form
from .variation import apply_rest, compile_variation, resolve_instrument_spans, transform_pitches
from .variation_fill import compile_fill
from .variation_period import compile_period


def catalog():
    return dict({name: info["range"] for name, info in SAMPLED.items()}, **{name: (0, 127) for name in SYNTH_PITCHED})


def _drums(part):
    return part.get("type") == "drums" or "groove" in part or part.get("accent") == "offbeat_tick"


def _drum_metadata(events):
    duplicates, result = {}, []
    for event in events:
        ordinal = duplicates.get(tuple(event), 0)
        duplicates[tuple(event)] = ordinal + 1
        result.append({"ordinal": ordinal, "window": None, "tones": []})
    return result


def compile_variations(song, compile_base, parse_absolute):
    """旧情報を保持し、変化したパートだけに内部描画metadataを追加する。"""
    occurrences = expand_form(song)
    plan = compile_variation(song, occurrences, pitched_catalog=catalog(), available_voices=set(PERCUSSION) | set(SYNTH_DRUMS))
    spans = resolve_instrument_spans(song["parts"], occurrences, plan, pitched_catalog=catalog())
    plain = {k: v for k, v in song.items() if k != "variation"}
    baseline = compile_base(plain)
    if not any(rule.intervals for rule in plan.rules):
        return baseline
    compiled = deepcopy(baseline)
    parts = arrangement.effective_parts(song)
    compiled.update(effective_parts=parts, event_metadata=deepcopy(baseline.get("event_metadata", {})))
    beats, bars = compiled["beats_per_bar"], compiled["bars"]
    timing = dict(song, beats_per_bar=beats, bars=bars)
    old_meta = deepcopy(baseline.get("event_metadata", {}))
    for name, events in baseline["notes"].items():
        if name not in old_meta:
            old_meta[name] = arrangement._metadata(parts[name], events, baseline)
    origins = {name: list(range(len(events))) for name, events in baseline["notes"].items()}
    changed = []

    def occurrence(beat):
        return arrangement._occurrence(beat, occurrences, beats)

    for name in reference_order(song["parts"], reference_fields=("copy", "source")):
        part = parts[name]
        rules = [r for r in plan.rules if r.part == name and r.intervals]
        dependency = part.get("copy", part.get("source"))
        if not rules and dependency not in changed:
            continue
        pitched = not _drums(part)
        kind = "notes" if pitched else "rhythm"
        old_events = baseline[kind][name]
        events = deepcopy(old_events)
        event_origins = list(range(len(events)))
        original_metadata = old_meta[name] if pitched else _drum_metadata(old_events)
        metadata = deepcopy(original_metadata)
        own_pitch = any(r.action in ("octave_up", "instrument") for r in rules)

        def instrument(beat, name=name):
            return next(s for s in spans if s.part == name and s.start <= beat < s.end)

        def resolve(beat, raw, bar, instrument=instrument, rules=rules, part=part):
            span = instrument(beat)
            octave = int(any(r.action == "octave_up" and any(i.start <= beat < i.end for i in r.intervals) for r in rules))
            result = transform_pitches(part, raw, octave_up=octave, note_range=span.note_range, bar=bar)
            return result

        resolver = resolve if own_pitch or "copy" in part and dependency in changed else None
        if "copy" in part:
            source_name = part["copy"]
            source = compiled["notes"][source_name]
            selected = part.get("sections")
            events = compile_copy(part, song, occurrences, source, pitch_resolver=resolver,
                                  note_range=SAMPLED.get(part["instrument"], {}).get("range", (0, 127)))
            kept = [i for i, e in enumerate(source) if selected is None or occurrence(e[0])["name"] in selected]
            old_kept = [i for i, e in enumerate(baseline["notes"][source_name])
                        if selected is None or occurrence(e[0])["name"] in selected]
            destination_indices = {source_index: index for index, source_index in enumerate(old_kept)}
            event_origins = [destination_indices.get(origins[source_name][i]) for i in kept]
            source_meta = compiled["event_metadata"].get(source_name, old_meta[source_name])
            metadata = []
            for index, event in zip(kept, events, strict=True):
                meta = deepcopy(source_meta[index])
                occ = occurrence(event[0])
                left, right = occ["start_beat"], occ["start_beat"] + occ["bars"] * beats
                if meta["window"] is not None:
                    left, right = max(left, meta["window"][0]), min(right, meta["window"][1])
                meta["window"] = [left, right]
                metadata.append(meta)
        elif part.get("accent") == "counter":
            source = compiled["notes"][part["source"]]
            events = compile_counter(part, song, occurrences, compiled["harmony"], source, pitch_resolver=resolver,
                                     note_range=SAMPLED.get(part["instrument"], {}).get("range", (0, 127)))
            metadata = arrangement._metadata(part, events, compiled, source)
            slots = {(e[0], e[2], e[3]): i for i, e in enumerate(old_events)}
            event_origins = [slots.get((e[0], e[2], e[3])) for e in events]
        elif part.get("accent") == "phrase_start" and resolver is not None:
            events = compile_phrase_start(part, song, occurrences, compiled["harmony"], pitch_resolver=resolver)
        elif "style" in part and resolver is not None:
            compiler = compile_bass if part["role"] == "bass" else compile_chords
            events = compiler(part, song, occurrences, compiled["harmony"], pitch_resolver=resolver)
        elif pitched and resolver is not None:
            if "phrases" in part:
                events = compile_melody(part, song, occurrences, pitch_resolver=resolver)
            else:
                events = parse_absolute(part, timing, pitch_resolver=resolver)
                selected = part.get("sections")
                if selected is not None:
                    kept = [i for i, e in enumerate(events) if occurrence(e[0])["name"] in selected]
                    if len(metadata) == len(events):
                        # 選択前の旧情報(arrangementなし)は同じ添字で絞り込む。選択済みならそのまま対応する。
                        metadata = [metadata[i] for i in kept]
                        event_origins = [event_origins[i] for i in kept]
                    events = [events[i] for i in kept]

        for rule in rules:
            if rule.action == "period":
                section_names = {i.name for i in rule.intervals}
                # Cの曲頭時計を保ち、各出現を再コンパイルしない。
                target = dict(part, sections=sorted(section_names))
                period = compile_period(target, song, occurrences, compiled["harmony"], period_beats=rule.beats)
                combined = [(e, m, o) for e, m, o in zip(events, metadata, event_origins, strict=True)
                            if not any(i.start <= e[0] < i.end for i in rule.intervals)]
                for event, meta in zip(period["events"], period["metadata"], strict=True):
                    beat, _, duration, velocity = event
                    chord = compiled["harmony"][meta["harmony_index"]]
                    pitches = resolve(beat, chord["pitches"], int(beat // beats) + 1)
                    combined.append(((beat, [pitches[t] for t in meta["tones"]], duration, velocity), meta, None))
                combined.sort(key=lambda item: item[0][0])
                events, metadata, event_origins = map(list, zip(*combined, strict=True)) if combined else ([], [], [])
            elif rule.action == "fill_last_bar":
                filled = compile_fill(part, song, occurrences, events, every=rule.every,
                                      available_voices=set(PERCUSSION) | set(SYNTH_DRUMS))
                events = filled["events"]
                event_origins = list(filled["origins"])
                metadata = [{"ordinal": 0, "window": None, "tones": []} for _ in events]

        rests = [i for r in rules if r.action == "rest" for i in r.intervals]
        rested = apply_rest(events, rests, drums=not pitched)
        metadata = [deepcopy(metadata[i]) for i in rested.indices]
        event_origins = [event_origins[i] for i in rested.indices]
        events = rested.events
        generated_duplicates = {}
        for event, meta, origin, rest_window in zip(events, metadata, event_origins, rested.windows, strict=True):
            if rest_window is not None:
                prior = meta["window"]
                meta["window"] = ([max(prior[0], rest_window[0]), min(prior[1], rest_window[1])]
                                  if prior is not None else list(rest_window))
            if origin is not None:
                meta["ordinal"] = original_metadata[origin]["ordinal"]
                meta["draw"] = origin
            else:
                identity = [event[0], event[1], event[2:]]
                key = repr(identity)
                ordinal = generated_duplicates.get(key, 0)
                generated_duplicates[key] = ordinal + 1
                meta.update(ordinal=ordinal, generated=identity)
            if pitched:
                meta["instrument"] = instrument(event[0]).instrument
            # copyは元DSPのdrawや新規identityを継承しない。
            if origin is not None:
                meta.pop("generated", None)
            else:
                meta.pop("draw", None)
        effective_meta = [{k: v for k, v in m.items() if k not in ("draw", "generated", "instrument")}
                          for m in metadata]
        same_instrument = not pitched or all(m["instrument"] == part["instrument"] for m in metadata)
        if events == old_events and effective_meta == original_metadata and same_instrument:
            continue
        compiled[kind][name] = events
        compiled["event_metadata"][name] = metadata
        origins[name] = event_origins
        changed.append(name)
    if not changed:
        return baseline
    compiled["variation_parts"] = changed
    return compiled
