# Architecture

<!-- last-reviewed: 2026-11-09 -->

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

`render.compile_song(song)` is a pure structured-design compiler for valid song objects (raw or loaded). It returns `occurrences`, `notes` (part name → event tuples), `harmony` (timed chord dicts), `bars`, and `beats_per_bar`. `load_song` invokes it to validate harmony as well as melody; callers can use the returned harmony later for accompaniment. Nothing in the current renderer plays those chords. Styles, templates, variation, MIDI files and new mixing are outside this batch.

Part hashes retain the mix-only exclusions (`volume`, `pan`, `mute`, `solo`, `note`) and engine version. Structured hashes additionally include key, meter, form, sections, the part's phrases/grid and compiled note or drum events. Harmony edits invalidate stems conservatively even though harmony is currently silent. Legacy hashes and waveforms retain the old path.
