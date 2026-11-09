# Setup, tests and CI

<!-- last-reviewed: 2026-11-09 -->

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

## CI

`.github/workflows/ci.yml` runs on `windows-latest` for pushes to `develop`/`main` and PRs: ruff, `check_conventions.py`, pytest, and the PowerShell script tests. `.github/workflows/pr-automation.yml` provides `No hold label`, the optional `Merge approved` gate and closing `Closes #N` issues on merges into `develop` (copied from DXForgeEX; see `ReviewAndMerge.md`).
