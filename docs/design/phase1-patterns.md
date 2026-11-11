# Design: Phase 1 additional accompaniment patterns

<!-- last-reviewed: 2026-11-11 -->

- Status: Implemented for the subset below; spec3.6 and phase1 remain incomplete
- Decided: 2026/11/10, coordinator-approved batch3 proposals and amendments
- Issues: #34, #35, #36, #37, #38

## Goal and options

Extend the pure accompaniment compilers and connect them to the existing renderer,
without adding settings, public APIs, voices, a second renderer or template defaults.
At batch3 baseline `cb1c368`, these additional patterns were absent; this is planned
integration, not a claim of a newly reproduced integration defect.
Keeping the event tuples avoids duplicate DSP and preserves the old waveform paths.
Synth substitutes for sampled percussion would misrepresent the catalog and were rejected.

## Preserved contracts

The [first batch](phase1-first-batch.md) and [basic accompaniment](phase1-accompaniment.md)
contracts remain in force. One beat is a quarter note: 4/4=4, 3/4=3, 6/8=3;
strong beats are respectively 0/2, 0, 0/1.5. `expand_form`, timed `compile_progression`,
`compile_bass`, `compile_chords`, `compile_rhythm` and their tuple formats are unchanged.
Root precedes inversion; bass and ordered pitches follow it. Exact occurrence selection
means repeated A matches every A but excludes A'; A' uses source A without inferred variation.
Notation conflicts fail by field presence, including empty values. Validation precedes
sample access, output creation and cache lookup for both render and listen.
Generators remain pure, import no renderer, and report Japanese part/global-bar errors.
Catalog ranges are available without loading sound; synth range is 0..127.

Apply octave, then semitone transpose, then minimum octave-only range correction
(lower tie). Full chord voicings preserve inversion/extensions under one common octave
shift; impossible correction fails. Original harmony, selected occurrence and song ends
remain hard windows after swing/jitter/strum, gate and minimum20ms; no clipped duration
is enlarged afterwards. Release/reverb tails remain separate DSP behavior.

## Bass additions

Approval: `msg_62aeb3a8d037` (including the arpeggio amendment).
All three meters are supported. Union the grid with harmony boundaries; reset sequence
at each bar and boundary, consuming a boundary attack before continuing the grid.
Duration is next union onset/bar end minus onset, times .9, clipped to harmony/selection/song.
Base velocity90, strong factor1, weak.8, one final round/clamp1..127.

| Style | Grid | Ordered pitches |
| --- | --- | --- |
| octave_8th | .5 beats | root-12, root; ignores slash bass |
| walking | 1 beat | root-12, third, fifth; diminished fifth6, sus fourth5; ignores extensions/slash bass |
| arpeggio | .5 beats | ordered inverted harmony.pitches minus12, including every extension |

For walking segments with at least two attacks, the last attack approaches the immediately
following harmony root-12 from one semitone below only if that next occurrence is selected.
The final harmony links to the first under the same rule. Never skip excluded gaps.
A one-attack segment stays root. Arpeggio corrects its entire ordered tone list by one
common minimal octave shift before cycling; its boundary attack is the first inverted tone.

## Chord additions

Approval: `msg_062518832358`. Base velocity90, strong factor1.2, otherwise1;
one final round/clamp1..127. All pitches originate from the full commonly corrected voicing.

| Style | Meters | Onsets and pitch order | Duration in beats |
| --- | --- | --- | --- |
| arpeggio_up | all3 | half-beat grid, ordered harmony pitches | .4 |
| broken | all3 | half-beat grid, indices [0,n-1,1,n-2,...] | .4 |
| strum | all3 | quarter beats, full original chord tuple | .8 |
| waltz | 3/4 only | beat0 lowest tone; beats1/2 all remaining tones | .8 |

Sequence phase resets per bar. Fractional harmony changes add no attack/reset;
the current bar step modulo tone count chooses the tone. Unsupported waltz meters fail.
`style=strum` alone supplies .02 seconds only when `part.strum` is absent; explicit0
or negative finite values remain valid. Only the renderer applies the per-tuple delay,
once; no compiler beat delay is added. New four styles restore the original harmony tone
index for synth seed identity after common range correction; tuple index still controls
strum delay. Old styles, absolute notes and degree notes retain their old seed/path.
Current harmony pitches have distinct values, so restoration is unambiguous.

## Rhythm additions

Approval: `msg_70cccc66b9b9`. All new five grooves support4/4 only. Other meters fail
at the first selected global bar (bar1 for empty selection). Table row/voice order is tie order.

| Groove | Ordered voice and onset lists within a bar |
| --- | --- |
| 16beat | kick[0,2]; snare[1,3]; hat[0,.25,.5,.75,1,1.25,1.5,1.75,2,2.25,2.5,2.75,3,3.25,3.5,3.75] |
| shuffle | kick[0,2]; snare[1,3]; hat[0,2/3,1,1+2/3,2,2+2/3,3,3+2/3] |
| bossa | kick[0,1.5,2,3.5]; rim[0,1.5,3]; hat[0,.5,1,1.5,2,2.5,3,3.5] |
| swing_ride | kick[0,2]; snare[1,3]; ride[0,1,1+2/3,2,3,3+2/3] |
| bongo_8beat | bongo_hi[0,.5,1.5,2,2.5,3.5]; bongo_lo[1,3]; tambourine[0,.5,1,1.5,2,2.5,3,3.5] |

Base95; hat/ride/tambourine factor.8, others1, strong0/2 further multiply1.2,
then one round/clamp. Every bar resets, exact selected occurrences only; no harmony
dependence, fills or variation. Drum3tuples have no gate/duration; one-shot tails remain.
Catalog and kit must contain every required real voice. No aliases or fake synth voices.
The synth-only default available voices of the pure compiler cannot supply sampled
ride/bongo/tambourine and fails explicitly; integration supplies actual catalog data.

Shuffle/swing_ride generate fixed2:1 once and permit only absent or finite0 song.swing.
Nonzero fails, without silent priority. Supplied swing_unit must be finite positive.
The other three new grooves use existing renderer swing once; the compiler validates
the identical pure transform for every onset inside its original [bar start,bar end),
rejecting overflow, nonfinite, negative-direction or end-boundary escape before audio/cache.
Empty selections still validate settings. The old four grooves are unchanged.

## Seeds, cache and verification

ENGINE_VERSION stays0.2. Approval `msg_44954385621a` adds internal hash context
`chord_pattern_dsp=1` only for role=chords and arpeggio_up/broken/strum/waltz.
Pre-integration develop6e1964c already accepted these styles but rendered without
the final tone-index/default-strum interpretation: its strum cache hash stayed
`1c73ca5ecd54fc42` across the integration while cached versus forced audio differed
by up to0.8998076915740967. Style/config/events alone cannot distinguish that DSP
change. The limited revision invalidates those four styles' earlier stems once;
all old-style hashes and engine0.2 remain unchanged, with no new song setting.
The repository helper warms real6e1964c caches for all four new and three old chord
styles, requires only the new chord stems to invalidate, then compares every normal
mix/stem with force and verifies mix-only reuse. The #24 event-local seed
contract remains independent of song/part ordering, cache, mix settings, Python hash
and processes, preserving simultaneous note identity. Volume/pan remain mix-only.

[BuildAndTest](../dev/BuildAndTest.md) describes the repository-only verification helper,
which retains comparison JSON/WAVs, full-array equality results and numeric seam measurements.
Historical verification retains intentional bass inequality, exact unaffected stems and
old/new mix reconstruction; no rebaseline or broad skip is permitted. New-style before
pairs explicitly omit generated parts because the styles did not exist at the baseline.
Sampled ride/bongo audio and subjective quality are not established by synth-only checks.

Issue34 cleanup is independently covered by [ReviewAndMerge](../dev/ReviewAndMerge.md#local-cleanup-cleanupmergedps1).
Later released batch3 workers were cleaned in actual operation; deletion of a real
transfer-origin worktree was not encountered and remains unverified. Fake-Orca safety
tests do not establish that real case.

## Remaining work

Spec3.6 still needs arrange phrase_start/offbeat_tick/counter and copy/countermelody,
then loop variation, three templates and phase1 listening. Neither spec3.6 nor phase1
is complete. MIDI files, usage mix and a new listening UI remain outside this batch.
