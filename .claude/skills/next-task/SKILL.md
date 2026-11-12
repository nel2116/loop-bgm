---
name: next-task
description: Check hands-on progress and propose unfinished work in loop-bgm. Use for 「ハンズオンの続き」「開発の続き」「次に行うべきタスクは?」「他にやるべきことは?」「次は何をする?」. It only proposes; it does not start the work.
---

# Proposing the next task

<!-- last-reviewed: 2026-11-09 -->

After this question the user usually follows with 「そのためのプロンプトを提示して」, so **only propose; do not start the work**. The instructions for the chosen task are written with the `orchestration-prompt` skill; that text delegates the work to Orca workers (`/orchestration`), so even a small task is not started from this conversation.

## User correction (2026-11-09)

The user's hands-on workflow is: inspect the agreed plan and progress, identify unfinished work, propose the next tasks, and present an orchestration prompt for the user to run in a separate session. When the user requests both selection and a prompt, complete both without asking again. Mentioning Orca orchestration while explaining this workflow does not authorize launching workers, creating issues, implementing, or merging. Execution requires a separate explicit request to execute the presented plan; a brief acknowledgement during planning is not that request.

DXForgeEX's development harness was imported to coordinate development: decompose the work, establish dependencies and shared contracts, run independent work in parallel, and integrate and verify the results through PRs, CI and review. Merely handing an arbitrarily small task to one worker misses that purpose. Plan from the unfinished phase as a whole before choosing a batch. Do not force parallelism where dependencies make it unsafe; explain a single-worker recommendation with concrete evidence.

## 1. Gather the state

```bash
git fetch -q origin
gh run list --branch develop --workflow ci.yml --limit 1 --json conclusion,headSha,displayTitle
gh pr list --state open --json number,title,labels,headRefName
gh issue list --state open --limit 50 --json number,title,labels
git worktree list
python Tests/check_conventions.py | grep '^warning:'   # docs not reviewed for over 90 days
```

- For each open PR, find out from its body and comments why it is still open (`hold` label, pending Codex findings, a worker still on it, ...).
- Collect pending checks from memory and from PR bodies' 「マージ後に確かめる項目」 and 「試聴メモ」, and the open listening-check issue of the current phase.
- Judge progress against the phases in `docs/spec.md` section 10.1. Items of the current phase without an issue yet are candidates too. At the end of a phase, the listening check (`docs/ListeningCheck.md`) is the next task.
- Read relevant handover records and design decisions to recover the user's agreed scope and deferred features. Separate historical progress from current evidence. Do not treat work an agent started without authorization as an approved priority. If an implementation term resembles a deferred user feature (for example internal MIDI pitch numbers versus MIDI file export), explain the distinction before proposing it.

## 2. Prioritize

Higher items first:

1. **develop's CI is failing** -> fix before anything else.
2. **Nearly finished work**: PRs with only a review step left, or Codex findings left to handle. Close these before starting new work.
3. **Bugs that stall development**: build, test, review, merge or cleanup failures. They affect all future work.
4. **The next item of the current spec phase** (feature progress).
5. **Making the tool easier to drive from AI/CLI** (widening what can be verified unattended: tests, checks, regression renders).
6. Other improvements. Reviewing stale docs (the `warning:` lines above) also goes here: one small PR per doc, procedure in the `writing-docs` skill.

Also note for each:

- **Changes the sound?** Then it needs a 「試聴メモ」; the user listens at the end of the phase, not per PR. Prefer work that can be verified by tests when the user is away.
- **Parallelizable?** Work that edits disjoint files can go to separate workers in parallel.
- **Size**: does it fit one PR? If not, show how to split it.

For the recommended batch, show prerequisites, tasks that can start together, dependent follow-up tasks, and the integration owner. Identify shared interfaces and file ownership before calling tasks independent. Shared-file edits require an owner or an explicit sequence. Use this dependency and ownership analysis as input to `orchestration-prompt`.

## 3. Present

Briefly, in Japanese:

- State summary (2-3 lines): develop CI, open PRs, pending checks.
- Candidate table (3-5 rows): task (issue number), reason, size, changes the sound, parallel partner.
- **Recommendation**: one (or a parallel combination) and why.
- If the user already requested the prompt, apply `orchestration-prompt` and present it in the same response. Otherwise end by asking 「この作業のプロンプトを作りますか?」 and stop. Neither path executes the plan.
