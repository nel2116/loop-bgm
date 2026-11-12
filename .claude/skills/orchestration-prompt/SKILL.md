---
name: orchestration-prompt
description: Write and present the instruction text that has an Orca coordinator (/orchestration) carry out loop-bgm issues. Use when the user says 「プロンプトを提示して」「〜のためのプロンプトを」「指示文を作って」, or when preparing to hand off work chosen with next-task. It only writes the text; it does not start workers or implement anything.
---

# Writing instructions for a coordinator

<!-- last-reviewed: 2026-11-09 -->

The user usually gets here from the `next-task` skill (「次のタスクを提示」→「プロンプトを提示」) and pastes the text written here into a new session that becomes the Orca coordinator. **Write and present it; never run it yourself.** The user once said 「勝手に進めないでプロンプトだけ提示して」. Do not start workers or begin implementing.

The text itself says that the work is delegated to Orca workers: it starts with "Use the /orchestration skill", and the template's roles are fixed: workers implement, open the PR, wait for CI, run `CodexReview.ps1 -Post` and fix findings; only the coordinator runs `-SetStatus`, and the user listens at the end of the phase.

The template is `template.md` in this folder. It deliberately does not copy Orca's own procedure (waiting, ask/reply/send, `worker_done`, recovery): the coordinator reads the guide that matches its Orca binary (`<ORCA_CLI_COMMAND or orca> skills get orchestration`). Do not add such steps back, in particular no `check --wait` loop, no restart of a silent worker, no blanket `worker-release`, and no fixed `--model`.

## 1. Settle what must be decided

Ask only about what cannot be read from the user's request.

- **Target batch**: use the phase-wide dependency and ownership analysis from `next-task` (including its user correction). Identify prerequisites, parallel tasks and dependent integration work. Do not reduce orchestration to a single-worker handoff without explaining why the remaining work cannot usefully run in parallel. Independence requires compatible interfaces as well as non-overlapping files.
- **Whether the user is present**: if absent, limit the work to what can be verified headless. Decisions beyond the spec become "the coordinator decides in the direction of a smaller scope and reports why".
- **Whether the sound changes**: then the worker writes a 「試聴メモ」 in the PR body; it does not block the merge. After CI and the Codex PASS, the coordinator runs `-SetStatus` through to the merge (no human approval).
- **Model**: none unless the user names one; then add `-Model <id>` to the `StartWorker.ps1` line.

## 2. Research and fill in the premises

Most of the value is in the premises section (what the coordinator verified), so workers do not redo the research.

```bash
gh issue view <N> --json title,body,comments
git fetch -q origin && git log --oneline -15 origin/develop
gh pr list --state open --json number,title,headRefName
```

- Check the cause location written in the issue against the actual code (write it as `file:line`); it may have changed since the issue was written.
- Write which section of `docs/spec.md` the issue implements.
- Mark anything unverified as (推定).
- Check that the edit scope does not overlap open PRs or leftover worktrees; if it does, write it under Ownership.

## 3. Fill in the template

- Fill in the `<...>` of `template.md`, and delete lines that do not apply as well as the comment and the last-reviewed line at the top.
- Write the completion conditions and Observable acceptance in a **verifiable form** (which command shows what, what happens before the fix). Never "it works".
- For a bug fix, include a condition that reproduces the failure before the fix.
- For hard work with several possible approaches, include a step where the approach is approved via ask before implementation, plus the "approach criteria". Leave them out for simple work.
- State what is out of scope, so the worker does not widen it.
- Fill in the template's coordination plan: dependency graph, shared contracts, ownership, integration responsibility, and observable batch completion. Specify which workers may start together and what evidence unlocks dependent tasks. Establish shared contracts before consumers implement against them. Follow the Orca guide's task-dependency reference when the resulting plan needs a DAG; do not invent CLI syntax in the prompt.

## 4. Present it

- Show the whole text in one code block (` ```markdown `) so it can be copied as-is.
- Before the block, 2-4 lines in Japanese with the key points: what is done by how many workers, whether the sound changes, that the merge is automatic after CI and the Codex PASS, and any points you were unsure about.
- Then wait for the user's reply.
