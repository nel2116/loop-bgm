# Design: Phase 1 within-loop variation

<!-- last-reviewed: 2026-11-13 -->

- Status: Implemented for the accepted minimal rules; phase1 remains incomplete.
- Decided: 2026/11/13, user ("Ok" to the coordinator's three-group request) and batch5 coordinator.
- Issues: [#57](https://github.com/nel2116/loop-bgm/issues/57) (section transforms), [#58](https://github.com/nel2116/loop-bgm/issues/58) (drum fill), [#59](https://github.com/nel2116/loop-bgm/issues/59) (period overlay), [#60](https://github.com/nel2116/loop-bgm/issues/60) (integration).

## Goal

Spec 3.7: the exported file repeats unchanged, so variation has to live inside one loop. The song gains a top-level `variation` list. Each rule names a part and an action; the renderer keeps one stem per part and runs the existing DSP once.

## Notation

| Rule | Fields | Targets |
|---|---|---|
| `{"section":"A'","part":"melody","do":"octave_up"}` | `section` exact expanded name, all occurrences | pitched parts |
| `{"section":"A'","part":"melody","do":"instrument","instrument":"bass"}` | `instrument` exact catalog name | pitched parts |
| `{"section":"B","part":"held","do":"rest"}` | | pitched and drum parts |
| `{"part":"drums","do":"fill_last_bar","every":8}` | `every` positive integer (bool rejected); no `section` | direct drums and grooves, not `offbeat_tick` |
| `{"part":"arp","do":"period","beats":3}` | `beats` positive finite (bool rejected); optional `section` | `role:chords` + `style:arpeggio_up` only |

Missing or `[]` means no change: `load_song` drops an empty list, so legacy songs and meters that variation rules do not support (such as 5/8) keep the old path exactly. `null`, wrong types, unknown fields/actions/names, overlapping rest with another action, overlapping duplicates, and more than one fill or period per part fail at load, before any sample access, output, cache or listen launch. Errors are Japanese and name the part and global bar. A valid rule whose selection is empty (or `every` larger than the song) is validated completely and then changes nothing: compiled data, hashes and audio stay exactly those of the song without `variation`. Rule order does not matter.

### Reset and meter table

| Action | Clock | Reset at occurrence/gap? | Meters |
|---|---|---|---|
| octave_up / instrument / rest | expanded occurrence intervals | n/a (interval-based) | all |
| fill_last_bar | global bars `every`, `2*every`, ...; incomplete final group gets no fill | no reset, no carry | 4/4, 3/4, 6/8; shuffle/`swing_ride` only in 4/4; nonzero `song.swing` rejected for the shuffle table |
| period | `t = c*P + i*P/n` from song start, `n` = tones in the current harmony | never; continues across bars, harmony, occurrences and gaps | all; `P = 4` proves asynchrony in 3/4 and 6/8 |

Fill tables (quarter-beat offsets inside the bar; L = low/kick family, H = high/snare family):

| Meter | L | H | H velocity offsets |
|---|---|---|---|
| 4/4 | 0, 2 | 2, 2.5, 3, 3.5 | -20, -10, 0, +10 |
| 3/4 | 0 | 1, 1.5, 2, 2.5 | -20, -10, 0, +10 |
| 6/8 | 0, 1.5 | 1.5, 2, 2.5 | -10, 0, +10 |
| 4/4 shuffle / swing_ride | 0, 2 | 2, 2+2/3, 3, 3+2/3 | -20, -10, 0, +10 |

Base velocity 95, L = v+15; rounded and clamped once. A fill replaces every drum onset in the target bar and keeps earlier one-shot tails. `bongo_8beat` (or an explicit `bongo_lo`+`bongo_hi` kit without kick/snare) uses real bongo voices; otherwise kick/snare. No fallback or aliases.

Period: a candidate equal to a harmony boundary uses the new harmony once; no extra attack is added at harmony boundaries. Held length is `min(.4, P/n, remaining harmony/occurrence/application/song)`. Example: triad, `P=3` gives onsets 0, 1, 2, 3, ...; four tones give 0, .75, 1.5, 2.25, 3, ...

## Application order

```
validate everything (variation, parts, references, catalog, meter, settings)
  -> raw events: base compiler / period (C) / fill (B)
  -> source: own octave + octave_up -> transpose -> common full-voicing range
     (range of the onset's instrument) -> instrument routing -> rest
  -> dependents in reference order: copy / counter use the source's final
     pre-DSP pitches and written occupancy
  -> destination: own octave/transpose/range, routing, rest
  -> existing render_part once (swing, jitter, strum, gate, hard windows, tails, mix)
```

Why the full voicing is resolved before a tone is picked: range correction on a single selected tone would move tones of one chord by different octaves and change the inversion. The resolver therefore receives the ordered full voicing at each onset and returns final full pitches; the existing tone selection then indexes into that list. Walking bass and lookahead are not recompiled per interval, so their phase is kept.

Section transforms: the onset decides instrument and pitch. An instrument or octave boundary leaves earlier held notes alone. Rest removes onsets and clips earlier written holds at the rest start; nothing is restored after the rest and DSP tails still ring. Catalog gain, range and release follow the onset's instrument; volume, pan, reverb and the rest of the DSP stay with the destination part. A copy without its own `instrument` inherits the source's instrument timeline; an explicit instrument overrides it. A copy never inherits source mix/DSP. Counter treats rests as written occupancy gaps; excluded source selections are not rests, and gate/release never create rests. A directly written countermelody is separate and unaffected.

## Implementation

`bgm/variation_integration.py` bridges the immutable plan of `bgm/variation.py` (A) to `compile_fill` (B) and `compile_period` (C). `render.compile_song` calls it only when `variation` is present. It compiles the song without `variation` first (the baseline), returns it unchanged when no rule has an interval, and otherwise recompiles only affected parts through the optional keyword-only `pitch_resolver` added to the existing compilers (`None` keeps the old formulas and order). `variation_parts` lists the parts whose events, metadata or instrument actually changed; other parts keep the baseline path, hash and audio.

Metadata per event keeps the existing ordinal/tones/window and adds `draw` (the renderer index of the original event, including events later removed by rest or fill) or `generated` (a stable identity for new events), plus `instrument` for pitched parts and `cut` (the rest start in beats) for notes a rest clips. `cut` limits only the end of the sounding note; the onset lower bound stays the existing `window`, so negative strum and jitter are kept. Compiled output never contains callables.

## Humanize audit

Existing behavior, unchanged: `render_part` seeds `np.random.default_rng` from the MD5 of the part name and draws `normal(0, .004*humanize)` seconds then `normal(0, 5*humanize)` velocity per event, in event order. `song.swing`/`swing_unit` delays odd subdivisions globally. Synth pitched/noise voices use `_synth_seed` from part, instrument, beat, ordinal and tone.

Under variation the renderer pre-draws the same pairs for every original event index, so a removed event still consumes its draw and surviving events get exactly the old values. Generated events (period, fill) draw from a local RNG seeded by SHA-256 of the destination name and their identity, using the same two distributions once. No second humanize pass and no extra randomness were added. Gap: spec 3.7's "細部のゆらぎ" is covered only by this existing mechanism; there is no per-section humanize control.

## Cache

Unaffected parts keep their old hashes exactly. Affected parts hash the effective part (without mix-only keys), actual events and metadata (draw/generated identity, instrument timeline) plus the existing audio context. Raw global variation rules, unrelated parts and source mix/DSP do not enter the hash. ENGINE_VERSION 0.2 and chord_pattern_dsp=1 are unchanged; no cache revision.

## Spec 3.7 coverage

| Item | State |
|---|---|
| A' octave up | Implemented (`octave_up`), numeric tests all meters |
| A' instrument change | Implemented (`instrument`), same stem, onset routing |
| Fewer parts | Implemented as `rest` per section/part |
| Fill every 8 bars | Implemented (`fill_last_bar`) |
| Patterns of different length | Implemented for `arpeggio_up` chords only (`period`) |
| Detail humanize | Existing mechanism only (see audit); unchanged |
| Template default variations | Not implemented (templates come later) |
| Subjective listening, real sampled ride/bongo WAV | Unverified |

Phase1 is not complete: three templates and the phase1 listening check remain.
