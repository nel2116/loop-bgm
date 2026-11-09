---
name: next-task
description: Propose what to work on next in loop-bgm from the repository's state (develop CI, open PRs and issues, spec phase progress, pending listening checks). Use when the user asks 「次に行うべきタスクは?」「他にやるべきことは?」「次は何をする?」. It only proposes; it does not start the work.
---

# Proposing the next task

<!-- last-reviewed: 2026-11-09 -->

After this question the user usually follows with 「そのためのプロンプトを提示して」, so **only propose; do not start the work**. The instructions for the chosen task are written with the `orchestration-prompt` skill; that text delegates the work to Orca workers (`/orchestration`), so even a small task is not started from this conversation.

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

## 3. Present

Briefly, in Japanese:

- State summary (2-3 lines): develop CI, open PRs, pending checks.
- Candidate table (3-5 rows): task (issue number), reason, size, changes the sound, parallel partner.
- **Recommendation**: one (or a parallel combination) and why.
- End by asking 「この作業のプロンプトを作りますか?」 and stop.
