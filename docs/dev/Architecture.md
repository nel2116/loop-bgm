# Architecture

<!-- last-reviewed: 2026-11-11 -->

The target design is `docs/spec.md` sections 2-9. This file describes what the code does **now**.

## Data flow

`songs/<id>/song.json` → `render.load_song` (defaults, validation, structured-song compilation) → per part: `parse_note_bars` / `parse_drum_bars` (events in quarter-note beats) → `render_part` (instrument voices placed at sample positions, swing, humanize, reverb send) → `fold_loop` (everything ringing past the loop end is added back onto the start, so the file loops without a seam) → mix (volume, pan, peak normalize to -1 dBFS) → WAV (+ MP3 via ffmpeg) → `check_loop` (jump and level difference at the seam).

Both render and listen use `load_song`. Every part, used phrase and used harmony bar is validated before sample access, output creation or cache lookup. Structured songs derive total bars and beats per bar from `structure`; matching explicit legacy timing fields are accepted, conflicting fields fail. No structural fields means the unchanged legacy path, including optional uninterpreted `key`.

## Modules (`bgm/`)

| Module | Role |
|---|---|
| `__main__.py` | CLI: `render`, `fetch`, `status`, `listen` |
| `paths.py` | repository paths, sample rate (44.1 kHz) |
| `theory.py` | note names ↔ MIDI, chord-name tokens, `parse_key` and `degree_to_midi` |
| `structure.py` | `meter_to_beats`, `grid_to_beats`, `expand_form`: quarter-note timing and source/occurrence positions |
| `melody.py` | `compile_melody`: section phrases to existing note event tuples |
| `harmony.py` | `parse_roman_chord`, `compile_progression`: timed chord metadata; no audio generation |
| `bass.py` / `chords.py` | Pure harmony-to-note generators for the supported part styles |
| `rhythm.py` | Pure meter/groove-to-drum generator; catalog voice names supplied as data |
| `arrange_copy.py` / `arrange_accents.py` / `arrange_response.py` | Pure graph/instrument/copy, phrase-start/tick and written-rest counter APIs |
| `arrangement.py` | Dependency-first integration, separate effective parts, parallel original-event identity and hard-window metadata |
| `instruments.py` | catalog: sampled instruments (VSCO 2 CE folder + filename regex, range, gain, Japanese name), percussion, synth instruments |
| `sampler.py` | sampled instrument: nearest root sample, resampling for pitch, velocity layers, round robin, release envelope |
| `synth.py` | synth voices (e-piano, bass, plucked strings by Karplus-Strong, pad, square/pulse/triangle/saw) and synth drums |
| `render.py` | song loading, parsing, per-part render with hash cache, loop folding, mix, seam check |
| `fetch.py` | sample download and verification against `data/vsco2-lock.json` |
| `listen.py` | minimal read-only local listening page, Web Audio loop playback, localhost HTTP server (`bgm listen`) |

## Prototype song format (current)

`parse_key` validates a tonic (A–G, optional #/b) and `major` / natural `minor`, returning a pitch class and mode. `degree_to_midi` converts 1–7 with an optional #/b and repeated commas (down) or apostrophes (up), requiring an explicit `base_octave`. The normalized tonic pitch class is placed in that octave: enharmonic keys, including B# / C and Cb / B, have identical pitches. Rendering uses base octave 4 for every degree instrument, plus relative octave and semitone transpose; harmony uses base octave 3. Japanese errors retain part and unfolded global bar; integration wraps `ValueError` as `SongError` for CLI handling.

Legacy notes remain `"C4:1 E4:0.5 r:0.5"` (pitch:beats, `r` rest, `C4+E4+G4:2` chord, `@80` velocity). Each entry of `bars` is a segment of whole bars; segments repeat until the song is filled. Drum parts (`"type": "drums"`) give one dict per bar: `{"kick": "x...x...", "snare": "..x."}` (`x` normal, `X` accent, `o` soft, `.` rest; the string length sets the grid).

Any of `meter`, `form`, `sections` activates the structured format and requires all three plus `key`. A note part uses either legacy absolute `bars` or degree `phrases` + `grid`. `parse_note_bars` dispatches phrases through `compile_melody`, preserving `(beat, [MIDI], duration, velocity)` and the DSP path. The source design is never rewritten. See [README](../../README.md) for syntax and [the decision record](../design/phase1-first-batch.md) for contracts and harmony semantics.

`render.compile_song(song)` is a pure structured-design compiler for valid song objects (raw or loaded). It returns `occurrences`, `notes` (part name → event tuples), `rhythm` (part name → drum tuples, including directly written drums), `harmony` (timed chord dicts), `bars`, and `beats_per_bar`. `load_song`, render and listen share compilation/validation before sample access, cache lookup or output creation. Generated styles dispatch by bass/chords role; grooves accept rhythm role with optional drums type, or drums type with omitted role. Notation conflicts are rejected by field presence, including empty fields. Instruments are checked against the catalog without loading samples, and catalog ranges are passed to pure pitched generators. No template defaults are inferred.

Generated bass/chords pass through the same `render_part` DSP as existing notes. After swing, timing jitter and per-note strum, onset is clamped to the original event's harmony/occurrence window. Notes starting at or beyond its end are skipped. Existing gate and minimum 20ms calculation is clipped to remaining window duration without reapplying the minimum; zero/negative results never reach DSP. Release/reverb tails remain. Absolute notes, degree melody and directly written drums retain their previous waveform path. Exact patterns, seed policy and pending scope are in [the accompaniment decisions](../design/phase1-accompaniment.md).

For the additional chord styles only, `render_part` defaults missing strum to .02 seconds for style=strum and restores original harmony tone indices for synth seeds; tuple indices still determine strum delay. Explicit0/negative strum remains unchanged. Compiler onsets have no strum delay. Shuffle/swing_ride supply fixed2:1 and reject nonzero song.swing; other new grooves validate the existing renderer transform before audio. Full schedules and supported meters are in [the additional pattern decisions](../design/phase1-patterns.md).

Part hashes retain the mix-only exclusions (`volume`, `pan`, `mute`, `solo`, `note`) and engine version. Structured hashes additionally include key, meter, form, sections, part style/groove and compiled note or drum events. Structural edits invalidate stems conservatively, including unchanged absolute stems; part style/groove edits affect that part. Mix-only edits reuse stem files. Engine 0.2 intentionally changes four formerly nondeterministic synth voices, with event-local seeds independent of cache state, unrelated songs/parts and mix settings; all other DSP remains unchanged. The new-style-only integration keeps engine0.2; internal hash context `chord_pattern_dsp=1` invalidates only the four new chord styles' pre-integration caches for their final seed/default-strum interpretation. Old-style hashes and waveform paths remain unchanged.


## Arrangement integration

Songs using copy/accent/source validate the complete reference graph (both copy and source), catalog, notation, type, roles, exact selection and generator meter/settings before rendering/listening side effects. Declaration order is irrelevant. `arrangement.compile_arrangements` uses the accepted pure APIs; full details and musical limitations live in [the arrangement decision record](../design/phase1-arrangements.md). Counter's explicit source is a directly notated melody. Independent directly notated arrange countermelody is compiled separately and retains direct-note DSP.

Only these songs add `effective_parts` and `event_metadata` to `compile_song`'s result. Effective dictionaries inherit only an absent copy instrument; input parts stay unchanged. Metadata parallels every pitched event with its original identical-event ordinal, original tone indices and optional unswung hard window. Copy chains propagate source windows and intersect destination occurrence/song bounds without adding harmony splits. Counter uses original written-duration gap/bar/harmony/occurrence/song bounds; phrase-start uses harmony/occurrence/song bounds. Destination pitch transforms and DSP each run once. Clipped gate/minimum20ms durations are never enlarged again; release/reverb remain separate.

Arrangement hashes use the effective destination instrument, actual events/windows/identity and existing destination audio settings. Source DSP and mix-only changes, and unrelated parts, do not enter dependent hashes. No internal arrangement cache revision is added: actual event/metadata/effective-instrument changes already distinguish previously ignored copy/phrase-start caches. The final regression helper verifies this using real738b980 caches. Every old song retains its previous compiled object, hash and waveform path, ENGINE_VERSION0.2 and chord_pattern_dsp=1.
