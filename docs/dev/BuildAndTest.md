# Setup, tests and CI

<!-- last-reviewed: 2026-11-11 -->

## Setup

```powershell
./setup.ps1                     # creates .venv (Python 3.12+) and runs pip install -e .[dev]
.venv/Scripts/python -m bgm fetch xylophone contrabass_pizz   # download only the instruments you need
.venv/Scripts/python -m bgm fetch                              # or all of them (about 1.2 GB)
```

`bgm fetch` downloads from the commit of VSCO 2 CE pinned in `data/vsco2-lock.json` and checks every file against its git blob SHA-1; a mismatch is deleted and fetched again. `curl` (shipped with Windows) does the transfer because `urllib` stalls on some Windows setups. Rebuilding the lock file from a GitHub tree listing: `python -m bgm.fetch lock <tree.json> <commit>`.

## Rendering

```powershell
.venv/Scripts/python -m bgm render <song> --no-mp3   # songs/<song>/song.json, or a path to a folder or song.json
```

Output: `songs/<song>/<song>.wav` (loop, 44.1 kHz/16 bit), per-part stems in `stems/` with a hash cache (unchanged parts are reused), the previous render in `history/`. MP3 needs `ffmpeg` on `PATH`. The render prints a seam check line (`つなぎ目 OK` or `注意: ...`).

## Local listening

Run `.venv/Scripts/python -m bgm listen [song] [--port 8765]` and open the printed localhost URL.
The song argument defaults to `proto_test`; like `render`, it accepts a song ID, folder or `song.json` path.
Render first: the listener reads `<song-folder>/<id>.wav` (`id` from `song.json`, defaulting to the folder name) and never renders or edits a song.
Only `/` and `/audio.wav` are served, on `127.0.0.1` only. Stop the server with Ctrl+C.
The page offers Web Audio loop playback, stop and WAV download. Keep the browser in the foreground.
Reload the page after rendering a new version (playback caches decoded audio until reload).
Remote access and the full listening UI are separate tasks.

## Tests

| Command | What | Time |
|---|---|---|
| `.venv/Scripts/python -m pytest -q -m "not slow"` | engine unit tests, hook tests | seconds |
| `.venv/Scripts/python -m pytest -q` | also renders a synth-only song (`slow`) | seconds |
| `python Tests/<name>_test.py` | one hook's tests (also collected by pytest) | seconds |
| `pwsh -NoProfile -File Tests/<Script>.Tests.ps1` | PowerShell script tests with fake `gh`/`codex`/`orca` | up to ~1 min |
| `python Tests/check_conventions.py` | file conventions | seconds |
| `.venv/Scripts/python -m ruff check .` | lint | seconds |

- Engine tests are `Tests/test_*.py`. They must not need downloaded samples: use the synth instruments (`bass`, `pad`, `square`, ...) and synth drums (`kick`, `snare`, `hat`, ...). A test that needs samples is marked `@pytest.mark.samples` and is skipped in CI.
- `Tests/` is one folder for everything: on Windows `tests/` and `Tests/` are the same folder.

## Phase 1 audio regression

`python Tests/verify_phase1_render.py` reproduces the phase 1 audio evidence without samples. It needs Git and the historical commit `17dddfed1fbda3f105737307896f78ebdd56a910` locally (`git fetch origin` in a full clone). It exports only that commit's `bgm/` into a disposable temporary directory and renders the historical `SYNTH_SONG` fixture in separate old/new processes. Issue #24 intentionally changes the fixture's synthesized bass from shared random state to stable event seeds (engine 0.2 invalidates old caches). The script requires that bass differs and that every other stem remains exactly equal. It reconstructs the old PCM16 mix from old stems, then replaces only bass and applies the same volume/pan, peak normalization and PCM16 encoding; both reconstructed mixes must exactly match their WAVs. Any unrelated stem or unexplained mix change fails. No checkout or root workspace is modified.

The script also renders C major/minor copies of `phase1_degrees`, checks third 64→63, a changed WAV, unchanged absolute stem, two identical forced mixes/stems per key, and loop checks. Artifacts and complete compiled notes/harmony are kept under `songs/phase1_degrees/build/verification/` (`--output` overrides it), including `verification.json`. Nonzero exit means failure. These are local evidence, not subjective listening; use [ListeningCheck](../ListeningCheck.md) at the phase boundary.

`python Tests/verify_accompaniment_render.py --output <external-folder>` renders the synth-only `phase1_accompaniment` through the CLI and retains before/major/minor WAVs, all stems, complete notes/harmony/rhythm JSON, CLI logs and `verification.json`. It checks every sample of mix/all stems across repeated forced renders, an interleaved song, partial cache and a separate process. Mix-only volume/pan edits must preserve cache hashes and stem mtimes. Key-only major/minor changes must affect melody/bass/chords and preserve absolute/drum arrays. The before pair omits the three newly generated parts; the same melody/absolute/direct-drum arrays must equal those rendered by pre-integration commit `f4dd9e2` (exported to a disposable temporary directory, no checkout changes). Loop checker results are recorded as measurements, not subjective listening or a requirement that every loudness warning passes. Run both helpers for final regression; no artifact input depends on a former worker checkout.

`python Tests/verify_patterns_render.py --output <external-folder>` is the batch3 final verification entry point. It uses only repository songs and Git baseline `cb1c368`, plus the two historical commits already required above; it needs no worker scripts or previous artifacts. It invokes both existing helpers unchanged, preserving their exact historical bass/mix policies. Nonzero exit means failure.

The helper renders `phase1_patterns` variants for all seven additional pitched styles and the three synth-capable grooves. Per variant it retains CLI commands/logs, before/major/minor WAVs, complete compiled events, every stem, full-array comparisons across repeated force/interleaved songs/extra parts/partial cache/separate process, mix-only hash/mtime reuse and local style/groove invalidation. Before means the same design with generated parts absent, not an alternative old groove. It also compares 151 complete old compiled objects and the old `phase1_accompaniment` mix/all stems exactly against prebatch3. `verification.json` records sample counts, seam jump, 99.9th-percentile within-loop difference, their ratio and start/end RMS/level delta for every new mix/stem; warnings are measurements, not subjective listening.

The helper also exports pre-integration `6e1964c`, warms real caches for all four new chord styles and pad/block/offbeat, retains before/after WAVs and hashes, and requires new-style-only invalidation followed by exact normal-versus-force mix/all-stem equality. Old-style hashes/audio and every unaffected stem remain exact; volume/pan edits still reuse hashes/mtimes. This verifies internal `chord_pattern_dsp=1` without changing engine0.2 or adding notation.

`Tests/test_batch3_integration.py` covers the complete meter table, exact A/A' selection, seed tone index versus tuple delay (including range correction), missing/zero/negative strum, renderer swing agreement/no double shuffle, held-note hard windows, pre-integration cache invalidation, and Japanese render/listen errors before audio/cache/output. Sampled ride/bongo/tambourine use the real catalog; their onset routing is tested with recording functions, not fake synth audio. Without installed samples, actual WAVs for `swing_ride`/`bongo_8beat` remain unverified. Use [the pattern record](../design/phase1-patterns.md) for approved schedules and remaining phase1 scope.

## CI

`.github/workflows/ci.yml` runs on `windows-latest` for pushes to `develop`/`main` and PRs: ruff, `check_conventions.py`, pytest, and the PowerShell script tests. `.github/workflows/pr-automation.yml` provides `No hold label`, the optional `Merge approved` gate and closing `Closes #N` issues on merges into `develop` (copied from DXForgeEX; see `ReviewAndMerge.md`).

`Tests/PrePr.Tests.ps1` checks PrePr's step selection, deduplication, failure handling, dirty-tree refusal and HEAD stamp using a temporary copy and fake commands. It does not run the selected checks or contact GitHub.


## Final arrangement regression

`python Tests/verify_arrangements_render.py --output <external-folder>` is the batch4 final entry point. It needs the current repository, Git and the historical commits used by the prior helpers, without any worker checkout or external artifact inputs. It forces the current checkout ahead of an editable install in the parent and supplies process-local PYTHONPATH to children; it never changes user environment variables. Git exports of historical bgm modules are disposable temporary directories, never worktrees or edits to the root checkout.

It retains CLI command logs, designs, complete occurrences/harmony/notes/rhythm and parallel window/identity/effective-part metadata, before/major/minor WAVs, all stems, dependency-edit snapshots and numeric loop metrics/warnings for4/4,3/4,6/8. Before removes only new generated copy/accent parts from the same example; the independent directly written countermelody remains. Every mix/stem sample is compared across repeated force, interleaved songs, unrelated insertion, partial caches and a separate process. Source notes/inherited-instrument edits must rebuild exactly their dependent stems; volume/pan/mute-only changes preserve all hashes/mtimes. Key-only edits change degree-derived notes and preserve absolute notes and their copy. Phrase-start can stay unchanged when the actual top chord tone is invariant (Iadd9/3 in this example).

The helper compares phase1_degrees/accompaniment/patterns compiled objects, stable hashes and full mix/all-stem arrays exactly with738b980. It warms previously accepted-but-ignored copy/phrase_start caches and checks limited natural invalidation plus exact unaffected stems and normal/force equality; no arrangement revision or old-audio rebaseline is needed. It then invokes verify_patterns_render.py, which invokes verify_phase1_render.py and verify_accompaniment_render.py unchanged, including the intentional historical bass difference and exact old/new PCM mix reconstruction. Nonzero exit means failure; verification.json is written only on complete success.

Tests/test_arrangement_integration.py separately covers graph/name/type/role validation, numeric fractional gaps and strong/offbeat schedules, exact selection/all-rest behavior, inheritance/override, pre-DSP source semantics, copied hard windows, original tone identity, minimum20ms clipping, destination swing and direct countermelody DSP. Render/listen CLI failures must be positioned Japanese messages without Traceback and precede sample/output/cache/server access. The A/B/C unit suites retain full pure API range/transform/metadata validation coverage. Actual sampled swing_ride/bongo WAVs and subjective listening remain unverified; see the arrangement record and ListeningCheck for phase-end questions. Phase1 remains incomplete.

## Final variation regression

`python Tests/verify_variations_render.py --output <external-folder>` is the batch5 final entry point, with the same checkout/PYTHONPATH rules as the arrangement helper. It renders the synth-only `songs/phase1_variations` example (A/B/A/A', 8 bars) in 4/4, 3/4 and 6/8 through the CLI and compares every mix/stem sample across repeated force, an interleaved song, partial cache and a separate process. Forced renders across a second boundary must give byte-identical stem WAVs. Volume/pan-only edits keep hashes and mtimes; inserting an unrelated muted part keeps all arrays. Before is the same design minus `variation`: every part not in `variation_parts` must be sample-identical. A minor-key copy changes degree notes only. It then runs `verify_arrangements_render.py` unchanged, which chains the three earlier helpers. Loop metrics are measurements, not listening results.

`Tests/test_variation_integration.py` covers source-then-copy order, rest before counter, no-op rules keeping compiled/hash/audio exact, period full voicing and phase across gaps, instrument inheritance, preserved RNG draws for removed events and validation before audio.
