# Architecture

<!-- last-reviewed: 2026-11-09 -->

The target design is `docs/spec.md` sections 2-9. This file describes what the code does **now**.

## Data flow

`songs/<id>/song.json` → `render.load_song` (defaults, validation) → per part: `parse_note_bars` / `parse_drum_bars` (events in beats) → `render_part` (instrument voices placed at sample positions, swing, humanize, reverb send) → `fold_loop` (everything ringing past the loop end is added back onto the start, so the file loops without a seam) → mix (volume, pan, peak normalize to -1 dBFS) → WAV (+ MP3 via ffmpeg) → `check_loop` (jump and level difference at the seam).

## Modules (`bgm/`)

| Module | Role |
|---|---|
| `__main__.py` | CLI: `render`, `fetch`, `status`, `listen` |
| `paths.py` | repository paths, sample rate (44.1 kHz) |
| `theory.py` | note names ↔ MIDI, chord-name tokens; standalone `parse_key` and `degree_to_midi` APIs (not yet used by rendering) |
| `instruments.py` | catalog: sampled instruments (VSCO 2 CE folder + filename regex, range, gain, Japanese name), percussion, synth instruments |
| `sampler.py` | sampled instrument: nearest root sample, resampling for pitch, velocity layers, round robin, release envelope |
| `synth.py` | synth voices (e-piano, bass, plucked strings by Karplus-Strong, pad, square/pulse/triangle/saw) and synth drums |
| `render.py` | song loading, parsing, per-part render with hash cache, loop folding, mix, seam check |
| `fetch.py` | sample download and verification against `data/vsco2-lock.json` |
| `listen.py` | minimal read-only local listening page, Web Audio loop playback, localhost HTTP server (`bgm listen`) |

## Prototype song format (current)

`parse_key` validates a tonic (A–G, optional #/b) and `major` / natural `minor`, returning a pitch class and mode. `degree_to_midi` converts 1–7 with an optional #/b and repeated commas (down) or apostrophes (up), requiring an explicit `base_octave`. The tonic pitch class is placed in that octave: enharmonic keys, including B# / C and Cb / B, have identical pitches. Invalid inputs and MIDI results outside 0–127 raise Japanese `ValueError`s; callers add part/bar context. Instrument defaults and renderer integration remain for later work.

Notes are absolute: `"C4:1 E4:0.5 r:0.5"` (pitch:beats, `r` rest, `C4+E4+G4:2` chord, `@80` velocity). Each entry of `bars` is a segment of whole bars; segments repeat until `bars` is filled. Drum parts (`"type": "drums"`) give one dict per bar: `{"kick": "x...x...", "snare": "..x."}` (`x` normal, `X` accent, `o` soft, `.` rest; the string length sets the grid). Phase 1 replaces this with scale degrees, roman-numeral chords and accompaniment patterns (spec section 3), keeping absolute notes as an escape hatch.
