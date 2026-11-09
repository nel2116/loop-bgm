---
name: ship-pr
description: Take a loop-bgm PR all the way through CI check -> Codex review -> handling findings -> re-review -> auto-merge via -SetStatus -> cleanup. Use when the user says 「マージして」「マージまで進めて」「PR を仕上げて」, when a PR you created meets its completion conditions, or when receiving a worker's PR as coordinator.
---

# Taking a PR to the merge

<!-- last-reviewed: 2026-11-09 -->

`CodexReview.ps1` and `CleanupMerged.ps1` automate the individual steps; this file says in what order, when and how far to run them. Mechanism details and verified pitfalls are in `docs/dev/ReviewAndMerge.md`.

Scheduling the auto-merge and the cleanup are done without the user asking each time (user policy). develop currently does not require human approval (`merge-ok`, #160), so it merges as soon as CI and `codex-review` pass (solo development, speed first; user policy 2026/11/03). Even if approval becomes required again, agents never add `merge-ok` (the PreToolUse hook `Tests/guard_merge_approval.py` blocks `gh` commands that add it). Never bypass the gates: no admin merges, no `gh pr merge --auto` on an unprotected branch, no removing the `hold` label, no adding `merge-ok`.

Run `.ps1` files with the PowerShell tool. Through the Bash tool they fail with a syntax error on the BOM line.

## 1. Check the completion conditions

Don't use `-SetStatus` until all of these hold (with no findings it schedules the auto-merge on the spot, and the PR merges once CI passes):

- All CI succeeded: `gh pr checks <N>`. If running, wait with `gh pr checks <N> --watch --interval 20`. When approval is required (variable `REQUIRE_MERGE_APPROVAL` is `true`), `Merge approved` correctly fails until `merge-ok` is added, so everything else passing is enough (`--watch` then exits with 1 because of it).
- The PR's completion conditions (in the issue and PR body) are met, with evidence (commands and output) in the PR.
- **Changes that alter the rendered audio** have a 「試聴メモ」 in the PR body (which example songs change and how, plus the before/after render command). The listening itself is not a merge condition; the user listens at the end of each phase (`docs/ListeningCheck.md`).
- If the PR changes regression baselines (`tests/baselines/`), the PR body says why the sound changed on purpose.
- Every earlier Codex finding is handled. For findings a worker did not fix, the coordinator has verified the reasons.

## 2. Run the review

```powershell
./CodexReview.ps1 -Pr <N> -Post     # 1 to a few minutes; comments the result on the PR
```

In orchestration the worker runs this in its own worktree and reports 「PR 準備完了」 in `worker_done`. The coordinator checks that report and the PR comment and does not review again. When the coordinator handles a PR without a worker, it runs it in a detached worktree created from origin/develop without switching the root checkout, and deletes the worktree afterwards. Waiting for CI and the review are independent and may run in parallel.

Handle each finding (lines `- [P0-P3] ...`), whatever its severity, in one of two ways:

- **Fix it**: first add a test that fails on the finding's input, confirm it fails before the fix and passes after (`git stash push -- <fixed files>` applies just the test to the old code). Then comment on the PR which finding was fixed how and what the test verifies.
- **Don't fix it**: if the finding is wrong or out of scope, reply on the PR with the reason. A reply alone does not pass the gate; if the same finding comes back in the next review, consult the user.

Workers verify and handle findings themselves and list unfixed ones with reasons in `worker_done`. The coordinator checks the reasons and, if they don't hold, sends them back (`send --to dispatch:<id>`; a finished worker gets it as a follow-up Task).

Pushing a fix detaches the `codex-review` status from the commit. Wait for CI and review again.

## 3. When findings don't converge

`-Post` prints the PR's FINDINGS count and, past 3, says to consult the coordinator with `ask`. When every fix reveals another hole, stop the loop. Example: the #124 hook that blocks `python3` tracked shell syntax with regexes and got a different finding six times in a row.

- If 2-3 reviews in a row find a new kind of problem in **the same part**, suspect the approach rather than the individual fixes.
- Consult the user on changing the approach or removing that part from the PR, with options and a recommendation. Don't ignore findings or bypass the gate on your own judgment.
- If there is an alternative to the removed part (e.g. removing the cause through a Windows setting), present it too.

## 4. Schedule the auto-merge

When the conditions hold and the last review had no findings, the coordinator runs (a hook blocks it in worker conversations, #195):

```powershell
./CodexReview.ps1 -Pr <N> -Post -SetStatus
```

If the PR has a PASS for the current head, it skips Codex, sets `codex-review` to success and schedules the auto-merge. Otherwise it reviews; with no findings it proceeds the same way, with findings go back to 2. Add `-ForceReview` to redo the review.

Then wait for the merge. Only when branch protection also requires `Merge approved` (approval required again), report 「承認待ち」 to the user with the PR number and the CI/Codex results, and have them add `merge-ok`.

```bash
gh pr view <N> --json state --jq .state     # until MERGED; wait with gh pr checks <N> --watch
```

When approval is required, pushing after approval removes `merge-ok` (`.github/workflows/pr-automation.yml`). After a fix, review again and then ask for approval again.

## 5. Cleanup and checks

```powershell
git switch develop      # if you are on the PR's branch
./CleanupMerged.ps1
```

- Before that, release a worker in a new worktree whose chat nobody needs any more (`worker-release --dispatch <id>`, or what `worker-list`'s `next` says); `CleanupMerged.ps1` keeps the worktree of any unreleased worker.
- Report warnings (`Orcaの削除が終わりませんでした`, `worktreeのフォルダが残っています`, `ブランチを削除できませんでした`) to the user as real problems.
- Confirm develop's CI succeeded: `gh run list --branch develop --workflow ci.yml --limit 1`.
- Run the PR body's 「マージ後に確かめる項目」 if any.
- The `close-issues` job closes the `Closes #NN` issues; close them by hand if it didn't.

## 6. Report

Briefly, in Japanese:

- The PR number and whether it merged
- Number of Codex findings and how they were handled (fixed; not fixed, with reasons)
- The cleanup result
- Remaining issues
