# Design: Phase 1 song templates

<!-- last-reviewed: 2026-11-13 -->

- Status: Accepted (implementation pending: loader/CLI worker B, template-file worker C)
- Decided: 2026/11/13, by the batch coordinator (contract proposed by the #66 worker and approved with three amendments: test split, missing-sample note, validation owner)
- Issues: [#66](https://github.com/nel2116/loop-bgm/issues/66)

## Goal

Spec 3.8 defines a song template (曲の型) as the bundle of instrumentation, accompaniment patterns, tempo range and default variation; spec 7.2 has `bgm new <曲ID> --style <型>` create a design skeleton from it; spec 10.1 asks for the first three in Phase 1. This record fixes the template file format, the meaning of song-level `style`, exactly what `bgm new` writes and refuses, the contents of the first three templates, the sample songs and the tests, so that the loader/CLI worker (B) and the template-file worker (C) can implement without guessing.

## Current state

As of develop `efe7f0e`:

- `templates/` does not exist. `bgm/__main__.py` has `render`, `fetch`, `status`, `listen`; there is no `new`.
- `load_song` (`bgm/render.py:46`) accepts song-level `style`, `title` and `usage` and nothing reads them. Verified for `style`: with the three drafts below, `compile_song` returns identical notes with and without song-level `style`.
- Part-level `style` already means the accompaniment pattern: bass `root_whole/root_quarter/root_fifth/octave_8th/walking/arpeggio` (`bgm/bass.py`), chords `pad/block/offbeat/arpeggio_up/broken/strum/waltz` (`bgm/chords.py:6`); `style` requires `role` bass/chords (`bgm/render.py:183-189`).
- Grooves (`bgm/rhythm.py`) use fixed voice names (kick, snare, hat, rim, ride, bongo_hi, bongo_lo, tambourine). `kit` only lists allowed voices; it does not rename them, so a groove cannot play `timpani`.
- Catalog (`bgm/instruments.py`): there is no sampled guitar; `nylon_guitar` is a synth. There is no electric guitar, which is why `pop_groove` is not among the first three.
- Without samples, `bgm render` of a song that uses a sampled instrument fails with an uncaught `FileNotFoundError` (`bgm/sampler.py:83`): measured on a draft acoustic song in a worktree without `samples/`, the output was a traceback ending in `FileNotFoundError: 音源 flute がありません。`bgm fetch` を実行してください`, exit code 1, and an empty `stems/` folder left behind. No synth substitution happens.

## Options

### A. Template = metadata + a literal song skeleton (chosen)

The four spec 3.8 defaults are written directly as the song fields they become. `bgm new` copies the skeleton and adds `id` and `style`. One format to learn; whatever the loader accepts, a template can say; nothing to merge.

### B. Template = separate default tables (instruments per role, styles per role, ...) that `bgm new` assembles into a song

Needs its own schema and an assembly step that duplicates part semantics (role, style/groove compatibility, kit, sections). More code and more ways for the template and the song to disagree.

### C. Templates with inheritance or merging (a song keeps `style` and inherits unspecified fields at render time)

Makes song-level `style` affect audio, hides values from the AI that edits `song.json`, and needs merge rules. Rejected by the issue's scope (no inheritance or merging).

## Decision

### Template file format

`templates/<name>.json`, UTF-8 without BOM, one JSON object with exactly these keys:

| Key | Type | Meaning |
|---|---|---|
| `name` | string | Template name; must equal the file stem (`acoustic` for `templates/acoustic.json`). |
| `ja` | non-empty string | Japanese name for listings and messages. |
| `tempo_range` | `[min, max]`, two integers, `min <= max` | Recommended tempo range (spec 3.8). Informational for the AI; `bgm render` does not enforce it on songs. |
| `song` | object | The design skeleton, written exactly as fields of `song.json`. |

Where the spec 3.8 defaults live:

| Default | Location |
|---|---|
| Instrumentation per role | `song.parts[*].instrument` (and `kit` / direct drum voices for rhythm) |
| Accompaniment pattern / groove per role | `song.parts[*].style` (bass, chords), `song.parts[*].groove` (rhythm) |
| Tempo range and default tempo | `tempo_range`; `song.tempo` is the default and must lie inside `tempo_range` |
| Default key, meter, form, sections | `song.key`, `song.meter`, `song.form`, `song.sections` |
| Default variation | `song.variation` (rules from `docs/design/phase1-variations.md`) |

`song` also carries `master` and per-part mix fields (`volume`). `song` must not contain `id`, `style`, `title` or `usage`: `bgm new` adds `id` and `style`, and the AI fills `title`/`usage` later. No inheritance, no merging, no references between templates.

Validation is done by B's `bgm/templates.py` when a template is loaded (by `bgm new` and by tests): the top-level keys are exactly the four above (unknown or missing keys are errors); `name` equals the stem; `ja` is a non-empty string; `tempo_range` is two integers (bool rejected) with `min <= max`; `song` is an object without `id`/`style`/`title`/`usage`; `song.tempo` is a number inside `tempo_range`. The song itself is then checked by the existing `load_song`/`compile_song` after `bgm new` places it (B decides whether to also run them on load, for example on a temporary copy). Template names must not equal any part-level accompaniment style or groove name.

### Song-level and part-level `style`

- Song-level `style` is the name of the template the song was created from. It is a provenance note: the renderer, the cache hash, `compile_song` and validation do not read it, and `load_song` is not changed. Changing or deleting it changes nothing in the audio.
- Part-level `style` keeps its existing meaning (bass/chords accompaniment pattern) and nothing else.
- Because template names never equal accompaniment style or groove names (tested by C), a value can always be read unambiguously by where it sits.

### `bgm new`

Command: `python -m bgm new <曲ID> --style <型>`.

On success it creates `songs/<曲ID>/` and writes `songs/<曲ID>/song.json` containing the object `{"id": <曲ID>, "style": <型>, ...song}`: `id` first, `style` second, then the keys of the template's `song` in their template order, values copied unchanged. Written with `json.dumps(..., ensure_ascii=False, indent=2)` plus a trailing newline, UTF-8 without BOM. Nothing else is written (no history, stems, cache or audio). It prints to stdout:

```
作成しました: songs/<曲ID>/song.json（型: <型>）
```

and exits with 0. The same arguments always produce the same bytes.

Melody: the template contains a placeholder `melody` part with its instrument and `"grid": "1/8"`, whose `phrases` hold only rests (`.`, one per grid step, bars separated by `|`, one entry per section source), and `"note": "仮のメロディ（休符のみ）。度数で書き換える"`. A fresh song therefore loads, compiles and renders with accompaniment only; the AI replaces the phrases in step 6 of spec 7.4. `bgm new` does not generate phrases; they are part of the template file.

Refusals write nothing (no folder, no file), print one line to stderr and exit with 1. They are checked in this order:

| Case | stderr |
|---|---|
| `<曲ID>` does not match `^[a-z0-9_]+$` | `曲IDは英小文字・数字・_ だけで書いてください: <曲ID>` |
| `songs/<曲ID>` already exists (file or folder, even empty) | `曲フォルダ songs/<曲ID> はすでにあります。別の曲IDにしてください` |
| No `templates/<型>.json` (or `<型>` is not a plain name) | `曲の型 <型> はありません（使える型: acoustic / comical / drama_strings）` |
| The template fails validation or is not valid JSON | `曲の型 <型> のファイルが壊れています: <理由>` |

The list of usable types in the third message is the sorted stems of `templates/*.json` at run time (` / ` separated), not a hard-coded list. A missing `--style` stays an argparse usage error (exit code 2). `<理由>` is the Japanese message of the validation error.

### The first three templates

All three: meter `4/4`, form `["A", "A'", "B", "A"]`, sections A and B of 8 bars (32 bars per loop), `master` `{"reverb": "room"}`, and a rest-only `melody` part (8 rests per bar). Only existing catalog instruments, accompaniment styles, grooves and variation actions are used; no new DSP.

| Template | `ja` | `tempo_range` / `song.tempo` | Key | Parts | Variation |
|---|---|---|---|---|---|
| `acoustic` | アコースティック小編成 | 80–110 / 96 | C major | melody `flute`; guitar `nylon_guitar` (synth) chords `strum`; bass `piano` `root_fifth`; no percussion | A' melody `octave_up`; B guitar `instrument` → `piano` |
| `comical` | コミカル | 120–160 / 144 | C major | melody `xylophone`; chords `violins_pizz` `offbeat`; bass `bassoon_stac` `root_fifth`; drums `bongo_8beat`, kit `bongo_hi`/`bongo_lo`/`tambourine` | A' melody `octave_up`; drums `fill_last_bar` every 8 |
| `drama_strings` | ドラマチックな弦 | 70–140 / 112 | A minor | melody `violins`; arp `violas` chords `arpeggio_up`; horn `horn` chords `pad`; bass `cellos` `root_quarter`; timpani direct drums `x.......x.......` | A' melody `octave_up`; arp `period` 3 beats |

`drama_strings` has no fill: grooves cannot play `timpani`, and a fill on the direct timpani part would use the synth kick/snare, which does not fit an orchestral sound.

The `song` objects, exactly (`<rests>` stands for the placeholder: eight bars of `. . . . . . . .` joined with ` | `):

```json
{"acoustic": {
  "tempo": 96, "key": "C major", "meter": "4/4", "form": ["A", "A'", "B", "A"],
  "sections": {"A": {"bars": 8, "chords": "I | vi | IV | V | I | vi | ii V | I"},
               "B": {"bars": 8, "chords": "IV | V | iii | vi | IV | V | I | V"}},
  "master": {"reverb": "room"},
  "parts": [
    {"name": "melody", "role": "melody", "instrument": "flute", "grid": "1/8",
     "phrases": {"A": "<rests>", "B": "<rests>"}, "note": "仮のメロディ（休符のみ）。度数で書き換える", "volume": 0.5},
    {"name": "guitar", "role": "chords", "instrument": "nylon_guitar", "style": "strum", "volume": 0.4},
    {"name": "bass", "role": "bass", "instrument": "piano", "style": "root_fifth", "volume": 0.4}],
  "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                {"section": "B", "part": "guitar", "do": "instrument", "instrument": "piano"}]},
 "comical": {
  "tempo": 144, "key": "C major", "meter": "4/4", "form": ["A", "A'", "B", "A"],
  "sections": {"A": {"bars": 8, "chords": "I | vi | IV | V | I | vi | ii V | I"},
               "B": {"bars": 8, "chords": "IV | V | iii | vi | IV | V | I | V7"}},
  "master": {"reverb": "room"},
  "parts": [
    {"name": "melody", "role": "melody", "instrument": "xylophone", "grid": "1/8",
     "phrases": {"A": "<rests>", "B": "<rests>"}, "note": "仮のメロディ（休符のみ）。度数で書き換える", "volume": 0.5},
    {"name": "chords", "role": "chords", "instrument": "violins_pizz", "style": "offbeat", "volume": 0.35},
    {"name": "bass", "role": "bass", "instrument": "bassoon_stac", "style": "root_fifth", "volume": 0.45},
    {"name": "drums", "role": "rhythm", "groove": "bongo_8beat", "kit": ["bongo_hi", "bongo_lo", "tambourine"], "volume": 0.35}],
  "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                {"part": "drums", "do": "fill_last_bar", "every": 8}]},
 "drama_strings": {
  "tempo": 112, "key": "A minor", "meter": "4/4", "form": ["A", "A'", "B", "A"],
  "sections": {"A": {"bars": 8, "chords": "i | VI | III | VII | i | iv | V | i"},
               "B": {"bars": 8, "chords": "VI | VII | i | i | iv | v | VI | V"}},
  "master": {"reverb": "room"},
  "parts": [
    {"name": "melody", "role": "melody", "instrument": "violins", "grid": "1/8",
     "phrases": {"A": "<rests>", "B": "<rests>"}, "note": "仮のメロディ（休符のみ）。度数で書き換える", "volume": 0.5},
    {"name": "arp", "role": "chords", "instrument": "violas", "style": "arpeggio_up", "volume": 0.3},
    {"name": "horn", "role": "chords", "instrument": "horn", "style": "pad", "volume": 0.3},
    {"name": "bass", "role": "bass", "instrument": "cellos", "style": "root_quarter", "volume": 0.4},
    {"name": "timpani", "type": "drums", "bars": [{"timpani": "x.......x......."}], "volume": 0.4}],
  "variation": [{"section": "A'", "part": "melody", "do": "octave_up"},
                {"part": "arp", "do": "period", "beats": 3}]}}
```

Each template file is `{"name": <key>, "ja": ..., "tempo_range": [...], "song": <the object above>}`. These three drafts (with `id` and `style` added) passed the current `load_song` and `compile_song` in a temporary folder (melody 0 events; varied parts: guitar, drums, arp respectively). Volumes are starting values for the Phase 1 listening check, not tuned.

### Sample songs

One per template, following the existing `songs/phase1_*` convention rather than spec 11.6's `songs/examples/` (moving all sample songs is a separate decision): `songs/phase1_acoustic`, `songs/phase1_comical`, `songs/phase1_drama_strings`. Each is the `bgm new` output for its template (`id` = folder name, `style` = template name) with the placeholder melody replaced by a real degree melody and its `note` removed; all other parts, instruments, styles, grooves and variation rules stay as in the template. `title`/`usage` may be added.

### Tests and ownership

CI has no samples. Every test below runs on `load_song`/`compile_song`/file checks only; none renders sampled audio and none substitutes synths. Real renders of the sample songs, if written, are marked `samples` and `slow`.

Worker B owns `bgm/templates.py`, `bgm/__main__.py`, `Tests/test_templates*.py`, `docs/dev/Architecture.md`. B implements before C's files exist, so B's tests use temporary templates under `tmp_path` (B decides how the templates and songs roots are injected, for example keyword arguments on the functions or monkeypatching):

- the type list is the sorted stems of the templates folder;
- each validation error (unknown key, missing key, `name` ≠ stem, bad `ja`, bad `tempo_range`, `song.tempo` outside the range, `id`/`style`/`title`/`usage` inside `song`, invalid JSON) gives the 「壊れています」 message;
- `bgm new` success: file content and key order, stdout line, exit code 0, the result loads with `load_song` and compiles with `compile_song`;
- determinism: two runs into different folders give identical bytes;
- each refusal (bad id, existing folder including an empty one, unknown type, broken template) gives its stderr line and exit code 1 and creates nothing;
- song-level `style` is ignored: `compile_song` output (and the part cache hash) is identical with and without it.

Worker C owns `templates/*.json`, the three sample songs and `Tests/test_template_files*.py`:

- every pitched instrument is in `SAMPLED` or `SYNTH_PITCHED` and every drum voice in `PERCUSSION` or `SYNTH_DRUMS`;
- `tempo_range` equals spec 3.8 (80–110, 120–160, 70–140) and the contents match the table above;
- template names do not equal any accompaniment style or groove name;
- the melody placeholder phrases contain only `.` and `|`;
- the three sample songs load and compile, have `style` = template name, and their parts other than the melody phrases/`note` (plus their variation rules) equal the template's.

Integration tests, written by whichever of B and C merges second after merging develop into its branch, in `Tests/test_templates_integration.py` (under B's `Tests/test_templates*.py` prefix): the real type list is exactly `acoustic`, `comical`, `drama_strings`; and for all three real templates `bgm new` into a temporary songs folder, then `load_song` and `compile_song` succeed. The first to merge leaves a note in its PR that this test is still owed.

## Consequences

- New: `templates/acoustic.json`, `templates/comical.json`, `templates/drama_strings.json`, `bgm/templates.py`, the `new` command, three sample songs, the tests above. `docs/dev/Architecture.md` gains the template module and data flow (B).
- Unchanged: `load_song`, `compile_song`, the renderer, the cache, existing songs. Song-level `style` stays unread.
- Not changed here: rendering without samples still fails with an uncaught `FileNotFoundError` (no synth substitution); reported to the coordinator as a separate bug candidate.
- Open: the other five templates (Phase 5), `docs/patterns.md`, the scene table (spec 7.6), `bgm doctor`/`bgm instruments`, moving sample songs to `songs/examples/`, and tuning volumes by listening.
