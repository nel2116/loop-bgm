<!-- last-reviewed: 2026-11-05 -->

## Rules for every worker

- The repository is loop-bgm (GitHub nel2116/loop-bgm). Read the root `AGENTS.md` first (Claude Code loads it through `CLAUDE.md`) and follow it. Write PR bodies and reports in Japanese.
- Your worktree is a new top-level worktree created from origin/develop. First run `git fetch` and check it with `git merge-base --is-ancestor origin/develop HEAD` (if that fails, report to the coordinator with `ask`). Do not edit anything elsewhere (especially the root checkout F:\loop-bgm) and do not switch its branch. PRs target develop. Do not merge.
- Branch names are `<fix|feature>/issue-N-...`. If the name starts with `nel2116/`, rename it first with `git branch -m`.
- Commit messages and PR titles are `[<fix|add>] <Japanese summary> (#N)`. The PR body has the sections 「概要」「変更点」「動作確認」「自己点検」 and `Closes #N` (unless the task says otherwise).
- Commit and push at every milestone, so the work survives if you stop at a usage limit.
- Before creating the PR, run `./PrePr.ps1`. It runs the builds and tests the diff needs and prints self-check items; `gh pr create` is blocked by a hook until it passes. Write what you checked for each item in the 「自己点検」 section. Report results as the command and its actual output.
- After creating the PR, wait for CI with `gh pr checks --watch` in the foreground and fix failures. Do not end your turn while waiting.
- When CI passes, run `./CodexReview.ps1 -Pr <N> -Post` yourself, check each finding, and either fix it or reply on the PR with why not. After fixing, push and run CI and the review again. If `-Post` says to consult the coordinator with `ask`, stop fixing and ask.
- Only the coordinator runs `-SetStatus` (a hook blocks it in worker conversations).
- After a PASS, send 「PR 準備完了」 with `ask`, including the PR URL, the commands and their actual output. List any findings you did not fix, with reasons (the coordinator verifies them).
- Do not use the GUI (`orca computer`/computer-use). You cannot judge how music sounds: when a change alters the rendered audio, write a 「試聴メモ」 section in the PR body (which example songs change, where, how, and the command that renders a before/after pair). It does not block the merge; the user listens at the end of each phase (`docs/ListeningCheck.md`).
- Never write the name of the human-approval label (#160) in a `gh` command. Do not change user environment variables.
- Always stop the processes you started when you are done. Create temporary files under %TEMP% and delete them afterwards.
- Keep waiting without ending your turn until you get a reply saying you may send worker_done. If `ask` times out, wait again with `ask --resume` and the same message ID. If your turn did end, resume on the next `send`.
- When you approach a usage limit, commit and push your work, tell the coordinator what is done and what remains, then stop.
- When the context size warning appears (#256), finish the step in hand, commit and push, and write a handover to `%TEMP%\handover-issue-<N>.md` (the issue number, not the branch name: its `/` would be a folder separator): done, remaining, decisions approved by the coordinator, commands run with their results, and any uncommitted files. Then send `ask` with the subject 「引き継ぎ依頼」 and the file path, and wait. Do not keep working in the same conversation unless the coordinator replies that you should.
- If you find an unrelated bug while working, report it to the coordinator instead of fixing it yourself.
- In worker_done, write the PR URL, what you verified (commands and actual output), what you could not verify, and what to check after the merge.
