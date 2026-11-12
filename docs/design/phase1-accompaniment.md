# Design: Phase 1 accompaniment integration

<!-- last-reviewed: 2026-11-11 -->

- Status: Implemented for the subset below; phase 1 remains incomplete
- Decided: 2026/11/10, coordinator-approved batch 2 contract and amendments
- Issues: #24, #25, #26, #27, #28

## Goal and alternatives

Generate accompaniment from the existing compiled harmony and expanded form, preserving note/drum tuples and the established renderer. A second renderer or new pattern settings would duplicate musical interpretation and DSP; pure generators plus the existing renderer keep those responsibilities separate. No MIDI files, usage mix, template defaults or listening UI are added.

## Interfaces and validation

`bass.compile_bass(part, song, occurrences, harmony, *, note_range=(0, 127))` and `chords.compile_chords` return `(beat, [MIDI], duration, velocity)` events. `rhythm.compile_rhythm(part, song, occurrences, *, available_voices=None)` returns `(beat, voice, velocity)`. All are pure, deterministic, import no audio/renderer, mutate no input and report Japanese ValueErrors with part/global bar. Integration wraps those as SongError. Catalog names and note ranges are resolved without sample access. Synth range is 0..127, not a user setting.

Only existing part `style` (bass/chords) or `groove` (rhythm) selects generation. Explicit incompatible roles/types fail. Rhythm role accepts omitted/drums type; drums type accepts omitted/rhythm role. Style/groove and bars/phrases/grid conflict by presence, including empty values. No fallback for unknown style, groove, voice, unsupported meter or invalid selections. Render and listen share load/validation before samples, outputs or cache. `compile_song` exposes occurrences, notes, harmony, rhythm (including direct drums) and derived timing.

One beat is a quarter note. Supported meters are 4/4 (4 beats), 3/4 (3), 6/8 (3). Strong positions are 0/2, 0, 0/1.5 respectively. `sections` selects exact occurrence names: A excludes A', repeated A matches all A occurrences, A' harmony uses source A. No variation is inferred.

## Pitched patterns

Schedules reset on each global bar. Base velocity is finite 1..127, default90. Octave/transpose must be integers, excluding bool.

| Pattern | Positions within bar | Articulation |
| --- | --- | --- |
| bass root_whole | Bar start plus every harmony boundary | 1.0 |
| bass root_quarter | 4/4: 0,1,2,3; others: 0,1,2; plus harmony boundaries | 0.9 |
| bass root_fifth | 4/4 and3/4: root0/fifth2;6/8: root0/fifth1.5; plus boundaries | 0.9 |
| chords pad | Every harmony start | 1.0 |
| chords block | 4/4: 0,1,2,3; others: 0,1,2 | Duration0.8 beats |
| chords offbeat | 4/4: .5,1.5,2.5,3.5; others: .5,1.5,2.5 | Duration0.4 beats |

Bass schedules union with chord boundaries; a simultaneous fifth/boundary becomes one new root, subsequent grid roles remain. Bass duration reaches the next actual union event/bar end, times articulation, clipped to harmony/selection/song end. Whole reattacks every bar. Strong velocity factor1, weak .8, rounded/clamped once. Root is harmony.root minus12, ignoring slash bass; fifth is root+6 for diminished, otherwise+7. Apply octave then transpose, then minimum octave-only range correction, lower tie. Preserve pitch class; impossible correction fails.

Pad reattacks at boundaries. Block/offbeat retain fixed grids without added boundary onsets, choose the chord sounding at onset and clip to its end. Chord velocity strong factor1.2, otherwise1, rounded/clamped. Start from ordered harmony.pitches, preserving inversion/extensions; apply octave/transpose then move the entire voicing by a common multiple of12 into range, minimum absolute shift, lower tie. No individual folding or additional voice leading.

## Rhythm patterns

| Groove/meter | kick | snare | hat |
| --- | --- | --- | --- |
| 8beat /4/4 | 0,2 | 1,3 | 0,.5,1,1.5,2,2.5,3,3.5 |
| march /4/4 | 0,2 | 1,3 | — |
| march /6/8 | 0 | 1.5 | — |
| waltz /3/4 | 0 | 1,2 | 0,1,2 |
| ambient_none /all supported meters | — | — | — |

All other pairs fail. Base velocity95, kick/snare factor1, hat .8; strong positions multiply1.2, then single final round/clamp1..127. Stable beat ordering retains kick/snare/hat ties. Omitted kit uses synth names. Supplied kit is a catalog voice-name array containing all generated voices, without aliases/remapping. voices is existing per-voice volume/pan configuration (individual null accepted); validate finite numbers/names even for ambient_none. No new pan restriction, fills or random humanization in generators.

## Renderer boundaries and seeds

For generated bass/chords only, original harmony, selected occurrence and song ends define a hard window in unswung quarter-note time. Apply swing+jitter+per-note strum; clamp onset to window start, skip onset at/after end. Compute existing gate duration with minimum20ms, then clip to end minus onset; never enlarge a clipped short duration again or pass nonpositive duration to DSP. Negative finite gate/strum retain existing validation semantics. Release and reverb tails are distinct from held-note duration and remain unchanged. Absolute/degree/direct-drums retain the old path. Skipped chord tones keep their original chord index for seed identity.

Issue #24 removed the shared synth RNG: each unseeded primitive uses local default_rng(1234), with keyword-only seed=None on synth functions. Only bass, nylon_guitar, kalimba and noise_hit receive renderer event seeds. Seed is first128bits SHA256 of canonical JSON `["synth-v1", part.name, voice, original beat, duplicate ordinal, chord index, MIDI]`. Normalize numeric beats; duplicate ordinal counts identical events only. No song ID, unrelated parts, cache hash, mix-only fields, Python hash or process/global random state enters identity. Existing fixed drum seeds1..6 and seven deterministic pitched voices retain exact DSP. ENGINE_VERSION0.2 invalidates old caches; those four formerly nondeterministic voices intentionally change, not an unexplained rebaseline.

Hashes retain engine, all audio-affecting part configuration and compiled events plus structural context. Volume/pan/mute/solo/note remain mix-only exclusions. Key/form/chords conservatively invalidate structured stems, even absolute stems whose audio remains equal; style/groove invalidate the affected part only.

## Verification and remaining work

Reproducible helpers and artifacts are described in [BuildAndTest](../dev/BuildAndTest.md). The historical helper retains baseline17dddfed1fbda3f105737307896f78ebdd56a910, exact unaffected stems, intentional bass inequality and exact old/new PCM mix reconstruction accounting for normalization. It must pass; the earlier temporary historical-mix failure was repaired in #24, not waived. The integration helper compares against pre-integration f4dd9e2 and checks exact full arrays, partial/full cache, forced rendering, interleaved songs, independent processes, key-only changes and mix-only cache preservation. Dedicated tests cover common early-error validation, boundary clipping and original chord seed indices. Loop checker measurements do not establish subjective sound quality.

The formerly pending bass/chord/rhythm additions are now covered by [the additional pattern decisions](phase1-patterns.md). The later [arrangement integration](phase1-arrangements.md) implements the listed arrange patterns, copy and separately tested direct countermelody. Remaining work is variation, three templates and phase1 listening. No phase completion or user listening request is implied by these batches.
