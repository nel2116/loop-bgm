<!-- last-reviewed: 2026-11-05 -->

<!--
Template for coordinator instructions. Fill in <...> and delete lines that do not apply.
Distilled from earlier instructions (#10, #11/#107, #104, #116/#117).
-->
Use the /orchestration skill to act as coordinator and have <issue #N (one-line description)> carried out by <one worker / N workers in parallel>. You supervise the workers, verify any Codex findings they did not fix, and take it through to the merge. Report to the user in Japanese. <Whether the user is present, e.g. "The user is away until about 22:00, so do not use the GUI; go as far as the completion conditions can be verified headless.">

## Preparation (coordinator)
1. `git fetch` to update origin/develop and confirm develop's CI succeeded. If it failed, stop and report.
2. Run `./CleanupMerged.ps1` and bring the root develop up to date. Report any warnings (treat them as real problems). <Worktrees intentionally kept, with names and reasons, e.g. "PR #108 awaits a GUI check, so `issue-10-import-cli` is correctly left">
3. Read the procedure with `orca skills get orchestration` (once per conversation; grep it afterwards) and confirm Orca runs with `orca status --json`. New worktrees are created, so also read `references/placement-and-remote.md`.
4. Create one Run with `run-create --objective "<objective>"`.
5. Do not switch the root checkout (develop). Run `CodexReview.ps1 -SetStatus` from a detached coordinator worktree created from origin/develop, and delete that worktree afterwards.

## Starting workers
- Write the task spec below to a file and start it with `./StartWorker.ps1 -SpecFile <file> -Name <issue-N-short-name>`. The script always prepends the common rules (`docs/dev/WorkerRules.md`). Add `-Size small` for small jobs.
- If the start times out on agent_readiness, follow the recovery steps you receive and restart in the same worktree with `./StartWorker.ps1 -Task <task> -RetryOf <dispatch> -Worktree path:<path>`. Do not create a new worktree.
- If a worker does not respond, check with `./WorkerStatus.ps1` (`send` returns `ok` even to exited workers). If `exited`, write a handover and restart it.
- When a worker asks 「引き継ぎ依頼」 after the context size warning (#256), stop it with `worker-stop` and `worker-release`, then start a fresh worker in the same worktree: `./StartWorker.ps1 -SpecFile <original spec + the worker's handover file> -Worktree path:<worktree>`. If only a step or two remain (e.g. waiting for the merge), reply that it may finish instead.
- Start all workers before waiting. Wait with `check --wait --timeout-ms 3600000 --types "worker_done,escalation,question"` run in the background (`run_in_background`), not in the foreground: each foreground wake-up re-reads the whole context (#256).
- Answer questions within the spec. <If approach approval is needed: "When a worker proposes an approach via ask, approve it against the approach criteria below or send back what to change."> For decisions beyond the spec, <confirm with the user before answering / since the user is away, decide in the direction of a smaller scope and give the reason in the final report>.

## Common worker rules
`StartWorker.ps1` prepends `docs/dev/WorkerRules.md` to the spec; do not repeat it in the task spec. Write only what differs from the rules (such as GUI handling) in the task spec.
- <If a GUI check is needed: write numbered steps in the PR body under the heading `## GUI の確認手順`. The implementer does not check them; the coordinator hands the check to another worker with `start-gui-check.ps1 -Pr <N>`.>

## Task spec <A> (#N)

<Fix / Implement> issue #N: https://github.com/nel2116/loop-bgm/issues/N
(<one-line description of the issue>)

Read the body with `gh issue view N`.

### Premises (verified by the coordinator)
- <facts verified in the code, with `file:line`; mark guesses as (推定)>
- <the section of docs/spec.md this implements>

### Content
- Target: <files/folders that may be edited>
- Change: <what to change and how; the recommended approach, and that a different decision must be confirmed via ask before implementing>
- Constraints: <what to keep, e.g. zero warnings, do not change user environment variables, no exceptions on `async void` paths, follow the existing style>
- Ownership: <areas not to touch, to avoid conflicts with other workers>
- Observable acceptance:
  - <reproduction before the fix, if possible>
  - <what to verify after the fix; make headless checks into tests>
  - <what can only be checked in the GUI (mark "GUI check")>

### Approach criteria (only when approach approval is included)
- <criteria the coordinator uses to approve>
- <what is out of scope>

### Completion conditions
- <verifiable conditions; all CI succeeds; what the PR must state>

## Codex review and merge
The worker runs `./CodexReview.ps1 -Pr <N> -Post`, fixes the findings and sends 「PR 準備完了」 after a PASS. The coordinator then:
1. If any findings were left unfixed, checks whether the reasons hold. If not, sends them back with `send --to dispatch:<id>`.
2. After confirming CI success and the PASS:
   - <No GUI check: run `./CodexReview.ps1 -Pr <N> -Post -SetStatus`. A PASS for the same head exists, so Codex is not rerun; it sets `codex-review` to success and schedules the auto-merge.>
   - <GUI check needed: start the GUI check worker with `./.claude/skills/gui-check/start-gui-check.ps1 -Pr <N>`. If the `worker_done` summary is PASS, confirm its `head:` equals the current PR head; if not (pushed after the check), check again. If it matches, worker-release, `-Cleanup`, then `-SetStatus`. If NG, have the implementing worker fix it and repeat.>
   - It merges once CI and `codex-review` pass (human approval is not required). Neither coordinator nor workers add `merge-ok` (#160). A hook blocks `-SetStatus` in worker conversations (#195).
3. After the merge, run `./CleanupMerged.ps1` and check develop's CI. <Parallel: when one PR merges first and develop moves, have the other merge develop and rerun CI and the review.>

## Cleanup and report
- After each worker_done, check its content, then `worker-release`. Do not end your turn until `worker-list --terminal-state reclaimable` is empty.
- Finally, per issue, report in Japanese: the PR number, whether it merged, Codex findings and how they were handled, evidence (commands and output), unresolved items and what to check after the merge. File new bugs found along the way with the `create-issue` skill.
