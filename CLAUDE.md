# CLAUDE.md

<!-- last-reviewed: 2026-11-09 -->

@AGENTS.md

## Claude Code specifics

- A hook in `.claude/settings.json` checks every `Write`/`Edit` with `Tests/check_conventions.py --hook`. When it reports a violation, fix it (`--fix` handles BOMs) instead of working around it.
- In orchestrated work the implementing worker runs `CodexReview.ps1 -Pr <N> -Post`, fixes the findings and reports after a PASS; only the **coordinator** runs `-SetStatus` (a hook blocks it in worker conversations).
- Run `./CleanupMerged.ps1` without being asked after merges.
- Write edit scripts to a file in the scratchpad and run them by path; a heredoc through Git Bash loses backslashes in Windows paths.
- Don't re-read a file right after writing it.

# Compact instructions

When compacting, keep: the pitfalls in `AGENTS.md` and this file, which issues are open and their decisions, exact commands used, and any measured numbers. Drop: full logs, file contents already written to disk, and superseded attempts.
