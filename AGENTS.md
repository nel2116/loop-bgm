# AGENTS.md

<!-- last-reviewed: 2026-11-12 -->

Shared instructions for coding agents (Claude Code reads this through `CLAUDE.md`; Codex reads it directly, including in `CodexReview.ps1` reviews). Keep it short: it is a map, and the details live in `docs/`. Add a rule here only after a mistake has happened twice, and prefer a check in `Tests/check_conventions.py` or a hook over a sentence when the rule has no exceptions.

## Project

loop-bgm turns a text "design" of a song (`songs/<id>/song.json`) into a seamlessly looping BGM, rendered with CC0 samples (VSCO 2 CE, VCSL) and built-in synths. An AI agent writes and edits the design in conversation with a user who knows nothing about music; the program renders it, part by part, and checks the result. The agreed specification is `docs/spec.md` (Japanese); its phases (section 10.1) decide what comes next. The development harness (hooks, Codex review, workers) was copied from DXForgeEX (`F:\HAL\Self\DXForgeEX`) and is described in spec section 11.

## Where to read more

| When you touch... | Read |
|---|---|
| what to build, the song format, phases, open questions | `docs/spec.md` |
| module layout, data flow, what the prototype already does | `docs/dev/Architecture.md` |
| setup, commands, tests, CI | `docs/dev/BuildAndTest.md` |
| PR review, merging, `CodexReview.ps1`, `PrePr.ps1`, `CleanupMerged.ps1` | `docs/dev/ReviewAndMerge.md` |
| orchestrated workers, `StartWorker.ps1`, `WorkerStatus.ps1` | `docs/dev/WorkerRules.md`, `docs/dev/ReviewAndMerge.md` |
| changes the user has to listen to | `docs/ListeningCheck.md` |
| any Markdown doc: language, where a fact lives, last-reviewed date | `.claude/skills/writing-docs/SKILL.md` |
| recorded design decisions | `docs/design/` |
| continuing the hands-on, choosing unfinished work, preparing an orchestration prompt | `.claude/skills/next-task/SKILL.md`, then `.claude/skills/orchestration-prompt/SKILL.md` (proposal and prompt only; do not execute) |

## Commands

```powershell
./setup.ps1                                   # create .venv and install (once)
.venv/Scripts/python -m pytest -q -m "not slow"   # fast loop (seconds)
.venv/Scripts/python -m pytest -q                 # everything that runs without samples
.venv/Scripts/python -m ruff check .
python Tests/check_conventions.py                  # BOM / last-reviewed / no audio files
.venv/Scripts/python -m bgm render <song> --no-mp3 # render songs/<song>/song.json
./PrePr.ps1                                        # before gh pr create: runs what the diff needs
```

- Use `python`, never `python3` (on this machine it is the Windows Store stub and silently does nothing).
- Run `.ps1` files with the PowerShell tool; through Git Bash they fail on the BOM line.
- Samples (1.2 GB) are not in the repository and not in CI. Tests that need them are marked `samples`; everything else must run on synth instruments only.

## Rules that break the build

Checked by `Tests/check_conventions.py` (CI, and a Claude Code hook after every edit):

- `.ps1` files are UTF-8 **with BOM**; every other text file has **no** BOM. Fix with `python Tests/check_conventions.py --fix <file>`.
- No audio files in git (`.wav`, `.mp3`, `.ogg`, ...). The repository is public; samples and rendered audio stay local.
- Every tracked `.md` has exactly one last-reviewed line (`writing-docs` skill).
- `ruff check .` is clean (line length 140).

## Code conventions

- Python 3.12+, numpy for audio. Error messages shown to the user are Japanese and name the part and bar (`[melody] 3番目の小節: ...`).
- Rendering is deterministic: the same `song.json` gives the same audio (seeded randomness only).
- Commit messages, PRs, issues and code comments are in Japanese (commit subjects start with `[add]`, `[fix]` or `[chore]` and end with `(#N)`). Docs for agents are in English; `README.md` and `docs/spec.md` are Japanese.

## Definition of done

- `ruff`, `check_conventions.py` and the tests that touch the change pass. Report the command and its result, not "tests pass".
- New behavior has a test. Anything that changes rendered audio gets a 「試聴メモ」 in the PR body (`docs/dev/WorkerRules.md`); the user listens at the end of each phase, not per PR.
- Run `./PrePr.ps1` before `gh pr create` (a hook blocks the PR without a stamp of HEAD) and record its self-check items in a 「自己点検」 section of the PR body.
- PRs target `develop`. Merging is gated by CI and a Codex review (`docs/dev/ReviewAndMerge.md`). The worker runs the review with `-Post` and fixes the findings; only the coordinator runs `-SetStatus`. Never add the `merge-ok` label (a hook blocks it). Never use `gh pr merge --auto` on a branch without protection.

## Keeping sessions cheap

Every request resends the whole conversation, so the cost of a session is its context size times its number of requests.

- Wait with one blocking command, not with sleep-and-check loops: `gh pr checks <N> --watch` or `gh run watch <id>`, and run a long command in the foreground with a long timeout instead of reading its output every few seconds. Each check is a full-context request (measured: coordinators slept 5-14 times per session at about 200k tokens each).
- In Claude Code a hook warns when the context passes 120k tokens and again every 50k (`LOOPBGM_CONTEXT_WARN_TOKENS`, `LOOPBGM_CONTEXT_WARN_STEP`); hand over at the next good stopping point. Codex has no such hook; its user config sets `model_auto_compact_token_limit`.

In Claude Code another hook blocks a whole-file `Read` of a large file (over 600 lines or 30 KB) and of any `.jsonl` transcript: grep first and read a range. `python Tests/usage_report.py` shows consumption per conversation.
