# Design: Phase 2 render pipeline contracts

<!-- last-reviewed: 2026-11-13 -->

- Status: Implemented (#75)
- Decided: 2026/11/14, by the batch coordinator with the user (`usage` required, free-text scene descriptions moved to `scene`)
- Issues: [#75](https://github.com/nel2116/loop-bgm/issues/75)

## Goal

Phase 2 (spec 10.1) adds mixing by usage profile, more output formats and automatic checks (spec 5.4, 5.5, 6). Today `render_song` (`bgm/render.py:810`) does all of it in one function, so four wave 2 workers (mix, output, note checks, audio checks) would edit the same lines. This record fixes six contracts so each of them owns separate files:

1. the stages and their function signatures;
2. the layout of `songs/<id>/out/` and `songs/<id>/build/`;
3. the `build/notes.json` schema;
4. the `out/report.json` schema and the check interface;
5. the song-level `usage` field and the profile table;
6. the `bgm/loudness.py` API.

Issue #75 implements only the skeleton: the existing behavior moved into the stages, `out/` with the master WAV and `report.json`, `build/notes.json`, the loudness meter, the profile table with `usage` validation, and `check_loop` turned into the first two checks. **The mixed audio does not change.**

## Current state

As of develop `5093ea2`:

- `render_song` renders stems with the `part_hash` cache (`stems/cache.json`), mixes (`volume`, `pan`, `mute`, `solo`), peak-normalizes to -1 dBFS times `master.gain_db` (attenuation only), fades one-shots, writes `mix.json`, copies the previous master into `history/<mtime stamp>.wav` (+ `.json` from `last_song.json`, keeping 10), writes `songs/<id>/<id>.wav` (PCM_16), copies `song.json` to `last_song.json`, writes `<id>.mp3` through ffmpeg, and logs `check_loop`.
- `check_loop` (`bgm/render.py:772`) only logs: a jump `|x[0] - x[-1]|` above 1.5 x the 99.9th percentile of `|diff|`, or a start/end RMS difference (0.25 s windows) above 9 dB. Inputs shorter than 1 s are not judged.
- `usage` was not read. `bgm/templates.py:15` forbids it in templates. Three sample songs carry free Japanese text there (`phase1_acoustic`: 「カフェや日常の場面」, `phase1_comical`, `phase1_drama_strings`).
- No scipy; numpy and soundfile only.

## Options

### A. Stage modules with one owner each, a thin orchestrator (chosen)

`bgm/pipeline.py` calls one function per stage; each stage lives in its own module. Checks register themselves from two modules. Wave 2 workers edit only their module and its tests.

### B. Keep `render_song` and add hooks inside it

Fewer files now, but every wave 2 change still edits `render_song`, and the mix/output order stays implicit.

### C. Spec 2.1's final layout now (`song.py`, `cli.py`, `export.py`, `check.py` ...)

Moving `load_song` and the CLI touches the files of the parallel workers (#70, #74) and makes this PR unreviewable. The names below follow spec 2.1 where a module is new (`export.py`, `checks/`); the rest of the split is left for later.

## Decision

### 1. Stages

`render_song(ref, force=False, mp3=True, log=print)` keeps its signature and return value (the master path) and its sample preflight (#70). After the preflight it calls `pipeline.run(folder, song, force=force, mp3=mp3, log=log)`. Stages, in order:

| Stage | Function (module) | Input → output | Owner in wave 2 |
|---|---|---|---|
| load | `render.load_song(ref)` (unchanged) + `profiles.resolve(song)` | ref → `(folder, song)`, `Profile` | — |
| notes | `notes.build_notes(song)`, `notes.write_notes(folder, doc)` | song → notes document (section 3), written to `build/notes.json` | note checks (read only) |
| stems | `stems.render_stems(folder, song, *, force, log)` | → `dict[part name, float32 (n, 2)]`, after `fold_loop`, before volume/pan; cache unchanged | — |
| mix | `mix.mix_stems(song, stems, profile)` | → float32 (n, 2): volume, pan, mute, solo; wave 2 adds low cut, voice band | mix |
| master | `mix.finish(song, mixed, profile)` | → `(master float32 (n, 2), {"gain": float})`: peak normalize, `gain_db`, one-shot fade; wave 2 normalizes to `profile.lufs` | mix |
| write | `export.write_outputs(folder, song, master, profile, *, mp3, log)` | → `dict[kind, Path]` with at least `"wav"`: history rotation, `out/<id>.wav`, MP3, `last_song.json`; wave 2 adds OGG, long version, stems export | output |
| check | `checks.run_checks(ctx)` | `CheckContext` → `list[Issue]` (section 4) | note checks / audio checks |
| report | `report.build_report(song, metrics, issues)`, `report.write_report(folder, doc)` | → `out/report.json`; `report.measure(master, song)` gives the metrics | — |

`pipeline.run` also writes `build/mix.json` (`{"gain", "seconds"}`, unchanged content) and logs as today: the per-part stem lines, `書き出し: <path>（<s>秒, <t>s）`, and for loop songs the seam line (`  つなぎ目 OK（段差 …、音量差 … dB）` or `  注意: <message>` for each issue). Checks never modify audio and never raise for a musical problem; a crash in a check is a bug and propagates.

`check_loop(x)` stays in `bgm/render.py` as a wrapper over the same seam measurement, returning `(ok, message)` with today's text, for existing tests and verify scripts.

### 2. Output layout

```text
songs/<id>/
  song.json        design (tracked)
  last_song.json   design of the last render (unchanged place)
  history/         <stamp>.wav + <stamp>.json, newest 10 (unchanged place and rotation)
  stems/           per-part FLOAT WAV cache + cache.json (unchanged)
  build/
    notes.json     notes stage output (new)
    mix.json       moved from songs/<id>/mix.json
  out/
    <id>.wav       master, PCM_16 44.1 kHz stereo (moved from songs/<id>/<id>.wav)
    <id>.mp3       MP3 (moved; still ffmpeg in #75, soundfile in wave 2)
    report.json    check report (new)
    later: <id>.ogg (LOOPSTART/LOOPLENGTH), <id>_<N>min.wav/.mp3 (long version), stems/<part>.wav (export)
```

`history/` and `last_song.json` stay at the song folder: they are the design history of spec 3.9, not outputs. History copies the previous `out/<id>.wav`.

Old paths: when `pipeline.run` writes the master and `out/<id>.wav` does not exist yet but `songs/<id>/<id>.wav` does, the old master is rotated into `history/` exactly as a previous version would be. Then the old `<id>.wav`, `<id>.mp3` and `mix.json` at the song folder are deleted, with one log line `  古い場所の書き出しを片付けました: <names>`. All of them are gitignored render outputs.

`bgm listen <song>` serves `out/<id>.wav`; its message for a missing master names that path.

### 3. `build/notes.json`

Built from the same event lists the renderer receives (`compile_song` results for structured, arranged or varied songs, `parse_note_bars`/`parse_drum_bars` otherwise), before humanize, strum and window clipping. One event per sounding pitch (a chord gives one event per tone at the same position).

```json
{
  "song": "phase1_degrees",
  "version": 1,
  "tempo": 100,
  "beats_per_bar": 4,
  "bars": 8,
  "seconds": 19.2,
  "loop": true,
  "parts": [
    {"name": "melody", "role": "melody", "type": "notes", "instrument": "e_piano",
     "events": [
       {"bar": 1, "beat": 0.0, "time": 0.0, "seconds": 0.0, "midi": 60, "drum": null,
        "duration": 1.0, "velocity": 90, "instrument": "e_piano"}
     ]}
  ]
}
```

| Field | Meaning |
|---|---|
| `version` | schema version, integer, `1` |
| `seconds`, `loop` | loop length (`song_seconds`) and `song["loop"]` |
| part `role` | `part.get("role")` or `null`; `type` is `"drums"` for drum parts (`_is_drums`), else `"notes"`; `instrument` is the effective part instrument, `null` for drums |
| `bar` | 1-based bar in the unfolded song: `floor(time / beats_per_bar) + 1` (with 1e-9 tolerance) |
| `beat` | position inside the bar in quarter-note beats, 0 = downbeat |
| `time` | absolute position in quarter-note beats from the song start |
| `seconds` | `_swing(time) * 60 / tempo`: swung, without humanize |
| `midi` / `drum` | sounding MIDI number (octave and transpose already applied by the compilers) for note parts; drum voice name for drum parts; the other is `null` |
| `duration` | written length in beats (`null` for drums) |
| `velocity` | written velocity 1-127, before humanize |
| `instrument` | voice that plays the event: per-event variation instrument when present, else the part instrument; the drum voice name for drums |

Parts appear in `song["parts"]` order, events in renderer order. Floats are rounded to 6 decimals. Muted parts are included (checks decide whether to skip them). The file is written with `json.dumps(doc, indent=1, ensure_ascii=False)` plus a newline, LF, no timestamps.

### 4. `out/report.json` and checks

Exactly the spec 6.3 shape:

```json
{
  "song": "phase1_degrees", "version": 1, "passed": true,
  "metrics": {"lufs": -14.2, "peak_db": -1.0, "loop_seconds": 19.2},
  "issues": [
    {"level": "warning", "check": "seam_level", "part": null, "bars": [1, 8],
     "message": "終わりと始まりの音量差が +10.2 dB あります", "hint": "..."}
  ]
}
```

- `version` is the **report schema version** (`1`), not a history counter: a counter would make two renders differ.
- `passed` is true when no issue has level `error`.
- `metrics`: `lufs` = `loudness.integrated_lufs(master)` rounded to 0.1, `null` when not measurable; `peak_db` = `loudness.sample_peak_db(master)` rounded to 0.1, `null` for silence; `loop_seconds` = `len(master) / SR` rounded to 0.001. They are measured on the float master passed to the write stage. Wave 2 may add keys; it must not rename these three.
- Each issue has all six keys: `level` (`"error"` / `"warning"`), `check` (id, snake_case), `part` (name or `null` for the whole mix), `bars` (sorted unique 1-based bars, may be empty), `message` (Japanese), `hint` (Japanese or a song.json snippet, or `null`).
- Issue order: check registration order (notes checks, then audio checks, each in module order), then the order the check returns.
- Written with `json.dumps(doc, indent=2, ensure_ascii=False)` plus a newline. No timestamps or paths: two renders of the same song give the same bytes.

Check interface (`bgm/checks/__init__.py`, frozen after #75):

```python
@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning"
    check: str
    part: str | None
    bars: tuple[int, ...]
    message: str
    hint: str | None

@dataclass(frozen=True)
class CheckContext:
    song: dict           # loaded song (load_song result)
    profile: Profile
    notes: dict          # the build/notes.json document
    stems: dict          # part name -> float32 (n, 2), folded, before volume/pan
    master: np.ndarray   # float32 (n, 2), what the write stage received
    sr: int

def note_check(check_id): ...   # decorator: fn(ctx) -> Iterable[Issue]
def audio_check(check_id): ...  # decorator: fn(ctx) -> Iterable[Issue]
def run_checks(ctx) -> list[Issue]
```

- Note checks live in `bgm/checks/notes.py` and read only `ctx.notes`, `ctx.song`, `ctx.profile` (and the catalog). Audio checks live in `bgm/checks/audio.py` and may read everything. `checks/__init__.py` imports both modules once; adding a check edits only its module and its test file (`Tests/test_checks_notes.py`, `Tests/test_checks_audio.py`).
- A check function takes the context and returns issues; it decides on its own whether it applies (for example the seam checks return nothing when `song["loop"]` is false or the master is shorter than 1 s).
- #75 adds two audio checks, converted from `check_loop` with its current thresholds: `seam_click` (error, jump above 1.5 x the 99.9th percentile of `|diff|`, bars `[1, N]`) and `seam_level` (warning, start/end RMS difference above 9 dB, bars `[1, N]`). Spec 6.1's 3 dB threshold for the level step is wave 2 (audio checks), after listening.

### 5. `usage` and profiles

`bgm/profiles.py`:

```python
@dataclass(frozen=True)
class Profile:
    name: str                     # "video" | "game" | "trpg"
    lufs: float                   # target integrated loudness
    voice_band: bool              # cut 1-4 kHz in accompaniment parts
    loop_seconds: tuple[int, int] # recommended loop length range
    outputs: tuple[str, ...]      # standard outputs

PROFILES = {
    "video": Profile("video", -16.0, True,  (60, 120), ("wav", "mp3", "long")),
    "game":  Profile("game",  -16.0, False, (60, 180), ("ogg", "wav")),
    "trpg":  Profile("trpg",  -20.0, True,  (120, 300), ("ogg", "mp3", "long")),
}

def validate_usage(song) -> None   # raises ValueError with the Japanese message
def resolve(song) -> Profile
```

- `usage` is **required; there is no default** (user decision). `load_song` calls `validate_usage` and raises `SongError` when it is missing (`song.json に usage がありません。用途を video（動画）/ game（ゲーム）/ trpg（TRPGのセッション）のどれかで書いてください`) or not one of the three strings (`song.json の usage は video / game / trpg のどれかにしてください（いまは「…」です）`). Spec 3.2 marks `usage` as required.
- In #75 the profile is passed to the stages but changes nothing: no LUFS normalization, no voice band, no new outputs (`mp3` stays the CLI flag). `usage` does not enter `part_hash`, so adding it to a song does not rebuild stems.
- Song-level `scene` (new, optional): a free-text note about the scene the song is for. The program does not read it. `phase1_acoustic`, `phase1_comical` and `phase1_drama_strings` move their former free-text `usage` there and get `"usage": "video"`. Every other song in `songs/` gets `"usage": "video"` (`phase1_degrees` after #74 has merged, since #74 owns it).
- `bgm new <id> --style <type> --usage <video|game|trpg>`: `--usage` is a required argparse option with those choices (a missing or wrong value is an argparse usage error, exit code 2, nothing written). `templates.new_song(song_id, style, usage, ...)` writes `{"id", "style", "usage", ...song}` in that order. `scene`, like `title`, is per song and joins `SONG_FORBIDDEN_KEYS` (templates must not contain it); the AI adds it after `bgm new`.

### 6. `bgm/loudness.py`

Pure numpy, no new dependency.

```python
def k_weight(x: np.ndarray, sr: int) -> np.ndarray
def integrated_lufs(x: np.ndarray, sr: int = SR) -> float   # -inf when not measurable
def sample_peak_db(x: np.ndarray) -> float                   # -inf for silence
```

- `x` is float, shape `(n,)` or `(n, channels)`; channels are weighted 1.0 (L, R; surround weights are not needed).
- K-weighting per ITU-R BS.1770-4: the high-shelf and high-pass biquads derived for any sample rate from the analog prototypes used by libebur128 (shelf f0 1681.97 Hz, gain 4.0 dB, Q 0.7072; high-pass f0 38.135 Hz, Q 0.5003), which give the published 48 kHz coefficients. Filtering is done by multiplying the FFT of the zero-padded signal with the biquads' exact frequency response (no per-sample Python loop); the padding (1 s) holds the filter tail, which decays far faster.
- Gating per BS.1770-4: 400 ms blocks with 75 % overlap, absolute gate -70 LUFS, relative gate -10 LU, `L = -0.691 + 10 log10(sum of channel mean squares)`.
- Input shorter than one block, or with no block above the absolute gate (silence), returns `-inf`. The report writes `null` for it.
- Tests: EBU Tech 3341 case 1 (stereo 1 kHz sine, -23 dBFS peak, 20 s → -23.0 ± 0.1 LUFS), the same at -33 dBFS (→ -33.0), silence and a 0.3 s input (→ -inf), and `sample_peak_db` of a known array.

### Equality of the audio

The mix and master stages are the old code moved verbatim (same float32 operations in the same order). A test renders every synth-only song in `songs/` (phase1_accompaniment, phase1_arrangements, phase1_degrees, phase1_patterns, phase1_variations) both with a copy of the pre-#75 `render_song` mix code and with the pipeline and compares the samples of the PCM_16 WAVs. A verify script `Tests/verify_phase2_pipeline.py` does the same for the sample songs against a develop checkout's output and is marked/run only with samples.

## Consequences

- Wave 2 file ownership: mix → `bgm/mix.py`; output → `bgm/export.py`; note checks → `bgm/checks/notes.py`; audio checks → `bgm/checks/audio.py`; each with its own test file. `bgm/pipeline.py`, `bgm/checks/__init__.py`, `bgm/report.py`, `bgm/notes.py`, `bgm/profiles.py` and `bgm/loudness.py` are shared contracts: change them only by updating this record first.
- `--parts`/`--bars`/`--seam` (spec 5.6) will be options of `pipeline.run` that filter stems or slice the master before the write stage; not part of #75.
- Moving the master breaks any local script that reads `songs/<id>/<id>.wav`; the repository's users are updated in #75.
