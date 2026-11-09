# Design: Phase 1 first batch contracts

<!-- last-reviewed: 2026-11-09 -->

- Status: Implemented
- Decided: 2026/11/09, by coordinator under the user batch instruction
- Issues: [#14](https://github.com/nel2116/loop-bgm/issues/14), [#15](https://github.com/nel2116/loop-bgm/issues/15), [#16](https://github.com/nel2116/loop-bgm/issues/16), [#17](https://github.com/nel2116/loop-bgm/issues/17), [#18](https://github.com/nel2116/loop-bgm/issues/18)

## Goal and previous state

At develop `17dddfed1fbda3f105737307896f78ebdd56a910`, `render.parse_note_bars` emitted `(beat, pitches, duration, velocity)` and theory handled absolute names only. Preserve that representation and legacy waveforms. Avoid a second renderer or accompaniment syntax.

## Decision

One beat is a quarter note, including tempo. `bar_beats = numerator * 4 / denominator`; 4/4=4, 3/4=3, 6/8=3. Grid `1/n` spans `4/n` beats. Each phrase bar contains exactly `bar_beats/grid_beats` tokens (a bracket chord counts as one). Reject grids incompatible with the meter; no implicit padding. Meter/grid denominators are powers of two.

`structure.meter_to_beats(meter)`, `grid_to_beats(grid)`, `expand_form(song)` are the timing API. `expand_form` returns dicts with `name` (occurrence name), `source` (unprimed material name), `occurrence` (zero-based form index), `start_beat` (zero-based), `start_bar` (one-based global), `bars` (positive integer). ASCII A' references A for melody and harmony, even if an identical A' definition exists; conflicting primed definitions and undefined sources fail. Inputs are never mutated. Numeric times may be floats. Structure imports no renderer or instruments.

`theory.parse_key(key)` returns `(pitch_class, mode)`. `degree_to_midi(degree, key, *, base_octave)` places the normalized tonic pitch class in that octave: A minor octave4 tonic=69; B# major equals C major. Minor means natural minor. An accidental changes the scale pitch by one semitone. Japanese `ValueError`s gain location at the caller.

`melody.compile_melody(part, song, occurrences, *, base_octave=4)` returns existing note event tuples without importing structure. It checks key, grid, phrases and every used source phrase. Missing phrases fail unless excluded by `part.sections`; that list selects occurrence names (A does not select A'). No cycling or padding. Integration uses base octave4 for every instrument as one initial policy. Integer `part.octave` is a relative octave shift; integer transpose adds semitones after conversion. MIDI outside 0..127 fails. Velocity defaults90; `>` multiplies by1.2 and `<` by0.8, rounded/clamped1..127; base velocity is finite1..127. A chord suffix affects all its notes. `-` extends the immediately preceding sounding event across bars within one phrase, never after rest, at phrase start or across occurrences. `.` is rest. Bar errors include `[part] N番目の小節` with unfolded global N; fields without bars have Japanese field locations.

`harmony.parse_roman_chord(token, key, *, base_octave=3)` returns `token`, `degree` (1..7), `accidental` (-1/0/1), `role`, `quality`, `extension`, `inversion` (0/1), `borrowed`, `pitches`, `root`, `bass`. Root precedes inversion; bass/pitches follow inversion. Role is the resolved roman spelling and quality, retaining borrowing accidentals; extension/inversion are separate. Quality is major/minor/diminished/sus4, extension is a suffix or null.

`harmony.compile_progression(song, occurrences, *, base_octave=3)` adds `beat`, `duration`, `section` (occurrence name), `source`, `bar` (global one-based). Each section has exactly `section.bars` pipe-separated nonempty chord bars; whitespace-separated chords divide a bar equally. Harmony is data only, with no audible accompaniment. The final implementation imports B's `meter_to_beats`, aligning all accepted meters after D's initially independent development.

### Approved harmony semantics

The coordinator approved D's proposal via `msg_67f3ab3cfb90`; [PR #22](https://github.com/nel2116/loop-bgm/pull/22) records implementation and approval. Canonical major role spellings `I ii iii IV V vi vii°` track the current key. Their minor qualities are minor, diminished, major, minor, major, major, major. Thus C major I→C minor i, IV→iv, V remains major; explicit minor v remains natural-minor v. Native minor spellings are also accepted. Major iv is explicit borrowed minor, distinct from IV. Other case variants are rejected unless covered by these spellings or accidental-prefixed borrowing.

Leading b/# uses parallel-major roots and preserves written quality. C major and C minor bVII both mean B♭ major. Supported single suffixes are 7 (+10), maj7 (+11), sus4 (root+5+7 regardless of original quality), add9 (+14). Diminished triad+7 is half diminished; fully diminished seventh (+9) is unsupported. `/3` puts the actual chordal third in the bass; sus4/3 is rejected. For sus4, both quality and extension are `sus4`. No user setting is added for these choices.

### Render integration

Any of meter/form/sections activates the structured format, requiring all plus key. Reject conflicting legacy bars/beats_per_bar rather than ignoring them; accept identical redundant values. Within a structured song, note parts use either phrases+grid or legacy absolute bars, never both. Absolute parts coexist with degree parts, but absolute tokens cannot enter phrases and degree tokens cannot enter legacy bars. Old songs keep the old pipeline including optional legacy key behavior.

Load/validate completes all new compilation, including harmony, before sample access, output creation or cache lookup. Both CLI render and listen use that load path. `render.compile_song` exposes compiled occurrences/notes/harmony and derived timing without mutating its input. `parse_note_bars` remains the renderer's entry point and reuses the existing event representation. Cache hashes include key, meter, form, sections, phrases/grid, compiled events and engine version, retaining mix-only exclusions. Original source files and error positions are preserved.

## Options and consequences

A second parallel event type would increase integration work and regressions; reusing tuples preserves the DSP path. Quarter-note timing retains legacy tempo semantics. Uniform base octave4 is predictable while instrument-specific defaults remain a future decision. Conservative cache invalidation rebuilds absolute stems on key/harmony changes even when their audio stays identical. Accompaniment styles, variation, templates, MIDI files, new mixing and listening UI are outside this batch.

## Verification

`Tests/test_render_integration.py` covers key-only 64→63 and changed WAV, invariant absolute pitches/audio, identical forced mixes/stems, cache inputs, input preservation and Japanese CLI errors before render side effects. `Tests/verify_phase1_render.py` compares the historical synth fixture's complete mix/stem arrays against the prebatch commit in separate processes and retains local major/minor WAVs, loop checks and full compiled notes/harmony. Reproduction and artifact locations are in [BuildAndTest](../dev/BuildAndTest.md); subjective listening follows [ListeningCheck](../ListeningCheck.md) at the phase boundary.
