<!-- last-reviewed: 2026-11-09 -->

<!--
Template for coordinator instructions. Fill in <...> and delete lines that do not apply.
How to drive Orca (waiting, messages, recovery) is not written here: the coordinator reads the
version-matched guide. This template only holds what is specific to loop-bgm.
-->
Use the /orchestration skill to act as the Orca coordinator and delegate <issue #N (one-line description)> to <one Orca worker / N Orca workers in parallel>. Workers implement, open the PR, wait for CI, run `CodexReview.ps1 -Post` and fix the findings; you verify their reports and the findings they did not fix, run `-SetStatus` and take it through to the merge. Report to the user in Japanese. <Whether the user is present, e.g. "The user is away until about 22:00; go as far as the completion conditions can be verified headless.">

## Preparation (coordinator)
1. Resolve the Orca CLI (`ORCA_CLI_COMMAND` if set, otherwise `orca`), read `<cli> skills get orchestration` once, and follow it for starting workers, waiting, messages and recovery. New worktrees are created, so also read its `references/placement-and-remote.md`. Read `references/recovery-and-cleanup.md` only when a start fails or a worker's state is in doubt.
2. `git fetch` and confirm develop's CI succeeded. If it failed, stop and report.
3. Run `./CleanupMerged.ps1` and bring the root develop up to date. Report any warnings (treat them as real problems). <Worktrees intentionally kept, with names and reasons>
4. Do not switch the root checkout (develop). Run `CodexReview.ps1 -SetStatus` from a detached coordinator worktree created from origin/develop, and delete that worktree afterwards.

## Starting workers
- Write each task spec below to a file and start it with `./StartWorker.ps1 -SpecFile <file> -Name <issue-N-short-name>`. It prepends the common rules (`docs/dev/WorkerRules.md`), creates a new top-level worktree from `origin/develop` and uses `ORCA_CLI_COMMAND`. Add `-Model <id>` only when the user named a model.
- Start every independent worker, then end your turn; Orca wakes you with each question, escalation and `worker_done`. Follow any `next` a receipt or `worker-list` gives.
- If a start fails, do not rerun it: read `failedStage` and follow the recovery reference. Retry the same Task only as it says. `./StartWorker.ps1 -Task <task> -RetryOf <dispatch> -Worktree path:<path>` retries into an existing worktree (placement is not inherited); use it only when the receipt and `worker-show` show nothing of the failed start still runs there.
- Silence, a timeout or `unverifiable` liveness proves nothing; do not stop, retry or restart a worker on that alone. `./WorkerStatus.ps1` lists each worker's terminal state, `attention` and `next` to help you look; act on `next` or ask the user.
- Answer questions within the spec. <If approach approval is needed: "When a worker proposes an approach via ask, approve it against the approach criteria below or send back what to change."> For decisions beyond the spec, <confirm with the user before answering / since the user is away, decide in the direction of a smaller scope and give the reason in the final report>.
- A worker that hands over (`worker_done` failed, subject 「引き継ぎ依頼」, a handover file) has settled its assignment. Read the handover; use `send --to dispatch:<id>` for follow-up work. If a replacement is needed, read the recovery reference and inspect the Dispatch and receipt's `next` before release or reuse; settlement alone does not prove the agent stopped. Follow the guide's same-Task recovery procedure rather than starting a new Task to bypass a failed attempt.

## Coordination plan

- Goal: <the unfinished user-visible phase capability this batch advances>
- Dependencies: <prerequisites, tasks that start together, and dependent follow-ups; explain why if only one worker is useful>
- Shared contracts: <data structures, interfaces and behavior agreed before dependent implementation; who establishes them>
- Ownership: <each worker's files/modules, ownership of shared files, and sequence for conflicting edits>
- Integration: <who connects the results, which completed tasks unlock integration, and how develop updates are incorporated>
- Batch acceptance: <commands and observable behavior proving the combined result, beyond individual worker reports>

## Common worker rules
`StartWorker.ps1` prepends `docs/dev/WorkerRules.md` to the spec; do not repeat it in the task spec. Write only what differs from the rules in the task spec.

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
- Constraints: <what to keep, e.g. deterministic rendering, Japanese error messages naming the part and bar, do not change user environment variables, follow the existing style>
- Ownership: <areas not to touch, to avoid conflicts with other workers>
- Observable acceptance:
  - <reproduction before the fix, if possible>
  - <what to verify after the fix, as tests or commands with their expected output>
  - <if the rendered audio changes: what the 「試聴メモ」 must name (songs, bars, before/after render command)>

### Approach criteria (only when approach approval is included)
- <criteria the coordinator uses to approve>
- <what is out of scope>

### Completion conditions
- <verifiable conditions; all CI succeeds; what the PR must state>

## Codex review and merge
The worker runs `./CodexReview.ps1 -Pr <N> -Post`, fixes the findings and, after a PASS, reports 「PR 準備完了」 in `worker_done`. Then the coordinator (follow the `ship-pr` skill):
1. If any findings were left unfixed, checks whether the reasons hold. If not, sends them back with `send --to dispatch:<id>` (it arrives as a follow-up Task).
2. Confirms CI success and the PASS on the current head, then runs `./CodexReview.ps1 -Pr <N> -Post -SetStatus`. With a PASS for that head, Codex is not rerun; it sets `codex-review` and schedules the auto-merge. Nobody adds the human-approval label; a hook blocks `-SetStatus` in worker conversations.
3. After the merge, runs `./CleanupMerged.ps1` and checks develop's CI. <Parallel: when one PR merges first and develop moves, have the other worker merge develop and rerun CI and the review.>

Audio changes are not listened to per PR: the 「試聴メモ」 is collected for the user's listening check at the end of the phase (`docs/ListeningCheck.md`).

## Cleanup and report
- Workers in new worktrees stay open after `worker_done`. Release one with `worker-release` only once nobody will use its chat (normally after its PR merged), so `CleanupMerged.ps1` can remove its worktree; follow `next` where `worker-list` gives one.
- Finally, per issue, report in Japanese: the PR number, whether it merged, Codex findings and how they were handled, evidence (commands and output), unresolved items and what to check after the merge. File new bugs found along the way with the `create-issue` skill.
