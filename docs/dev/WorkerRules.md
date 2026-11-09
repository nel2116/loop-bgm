<!-- last-reviewed: 2026-11-09 -->

## Rules for every worker

- The repository is loop-bgm (GitHub nel2116/loop-bgm). Read the root `AGENTS.md` first (Claude Code loads it through `CLAUDE.md`) and follow it. Write PR bodies and reports in Japanese.
- Orca: use the executable in `ORCA_CLI_COMMAND` (plain `orca` only when it is unset) and read its guide once with `<that executable> skills get orchestration`. The guide and the preamble above these rules decide how you talk to the coordinator; these rules only add what is specific to loop-bgm.
- Your worktree is a new top-level worktree created from origin/develop. First run `git fetch` and check it with `git merge-base --is-ancestor origin/develop HEAD` (if that fails, `ask` the coordinator). Do not edit anything elsewhere (especially the root checkout F:\loop-bgm) and do not switch its branch. PRs target develop. Do not merge.
- Branch names are `<fix|feature>/issue-N-...`. If the name starts with `nel2116/`, rename it first with `git branch -m`.
- Commit messages and PR titles are `[<fix|add>] <Japanese summary> (#N)`. The PR body has the sections 「概要」「変更点」「動作確認」「自己点検」 and `Closes #N` (unless the task says otherwise).
- Commit and push at every milestone, so the work survives if you stop at a usage limit.
- Before creating the PR, run `./PrePr.ps1`. It runs the builds and tests the diff needs and prints self-check items; `gh pr create` is blocked by a hook until it passes. Write what you checked for each item in the 「自己点検」 section. Report results as the command and its actual output.
- After creating the PR, wait for CI with `gh pr checks --watch` in the foreground and fix failures.
- When CI passes, run `./CodexReview.ps1 -Pr <N> -Post` yourself, check each finding, and either fix it or reply on the PR with why not. After fixing, push and run CI and the review again. If `-Post` says to consult the coordinator, `ask` it and stop fixing.
- Only the coordinator runs `-SetStatus` (a hook blocks it in worker conversations), confirms CI and the PASS, and merges.
- Questions and decisions beyond the spec go to the coordinator with `ask`; then end your turn. Orca wakes you with the answer. Do not wait in a loop, `ask --resume` or `check --wait`.
- After a PASS, send `worker_done` with the subject 「PR 準備完了」: the PR URL, the commands and their actual output, the Codex findings and how each was handled (list unfixed ones with reasons; the coordinator verifies them), what you could not verify, and what to check after the merge. If the coordinator sends more work, it arrives as a new Task; report it with `worker_done` again.
- Do not use the GUI (`orca computer`/computer-use). You cannot judge how music sounds: when a change alters the rendered audio, write a 「試聴メモ」 section in the PR body (which example songs change, where, how, and the command that renders a before/after pair). It does not block the merge; the user listens at the end of each phase (`docs/ListeningCheck.md`).
- Never write the name of the human-approval label in a `gh` command. Do not change user environment variables. Do not pass `--model` to Orca unless the user named a model.
- Always stop the processes you started when you are done. Create temporary files under %TEMP% and delete them afterwards.
- When you approach a usage limit, or when the context size warning appears, finish the step in hand, commit and push, and write a handover to `%TEMP%\handover-issue-<N>.md` (the issue number, not the branch name: its `/` would be a folder separator): done, remaining, decisions approved by the coordinator, commands run with their results, and any uncommitted files. Then send `worker_done` with `--outcome failed`, the subject 「引き継ぎ依頼」 and `--report-path` set to that file. The coordinator decides whether to send you a follow-up or start a fresh worker.
- If you find an unrelated bug while working, report it to the coordinator instead of fixing it yourself.
