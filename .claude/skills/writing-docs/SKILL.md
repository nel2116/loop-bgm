---
name: writing-docs
description: Rules and procedure for writing or updating loop-bgm documentation for loop-bgm (AGENTS.md, CLAUDE.md, docs/dev/, docs/design/, skills, README.md) - language, where a fact lives, design decision records, and the last-reviewed date checked by Tests/check_conventions.py. Use when creating or editing any Markdown doc, recording a design decision, when check_conventions reports a `review` violation or a stale-doc warning, or when the user asks to review docs.
---

# Writing and updating docs

<!-- last-reviewed: 2026-11-08 -->

Policy decided with the user on 2026/11/08 (issue #237).

## Language

- **English by default** for every doc, mainly to save tokens (the same content in Japanese costs about 1.2-1.6x). This includes `AGENTS.md`, `CLAUDE.md`, `docs/dev/`, `docs/design/`, `docs/ManualVerification.md` and `.claude/skills/*`.
- **Japanese only for docs explicitly designated as human-read.** Designated so far: `README.md` (human overview; agent-facing details such as `build.ps1` parameters belong in `docs/dev/BuildAndTest.md`). Future engine-user docs or a public API wiki would also qualify. Add a doc to this list only when the user says so.
- Never write the same content in both languages; link to the one copy instead.
- What the docs tell agents to *produce* keeps the repo conventions: commit messages, PRs, issues and code comments stay Japanese even when the skill text is English.

## Where a fact lives

One fact, one place; everything else links to it.

| Content | Place |
|---|---|
| Map for agents, build-breaking rules, conventions | `AGENTS.md` (keep it short; add a rule only after a mistake happened twice) |
| Claude Code-only specifics | `CLAUDE.md` |
| How the engine/editor/tools work, build, test, review | `docs/dev/*.md` |
| Why something is designed the way it is | `docs/design/<topic>.md`, one decision per file |
| A repeatable procedure an agent runs | `.claude/skills/<name>/SKILL.md` |
| Steps that need a human to listen | `docs/ListeningCheck.md` |
| Human overview | `README.md` (Japanese) |

Prefer a check in `Tests/check_conventions.py` or a hook over a sentence when a rule has no exceptions.

## Design decision records (`docs/design/`)

Write one when a decision is made that the code alone does not explain (units, file formats, trade-offs between options). Decisions made in issue comments get copied here so agents don't have to read the issue.

- Copy `design-record.md` from this folder to `docs/design/<kebab-case-topic>.md` and fill it in: goal, options with trade-offs, decision, date, issue numbers, status.
- Status is one of `Proposed`, `Accepted` (implementation pending), `Implemented`, `Superseded by <file>`. After implementation the record stays as the archive of why; update the status, don't delete it.
- When a decision changes, edit the record (or supersede it) in the same PR that changes the code. Old statements left in issues are not corrected; the record is the source of truth.
- Link the record from the issue that discussed it, and from `AGENTS.md`'s table only if agents need it often.

## The last-reviewed date

Every tracked `.md` file has exactly one line of the form `<!-- last-reviewed: YYYY-MM-DD -->`, on a line of its own (put it just below the H1 title). `python Tests/check_conventions.py` fails on a missing, malformed, duplicated or future date and warns once the date is more than 90 days old.

- The date means **someone read the whole doc and checked it against the current code**, not that the file was touched. Editing one paragraph does not bump it.
- A new doc gets today's date.
- When quoting the marker inside a doc (like here), keep it inline in backticks, never on its own line, or the check counts it as a second marker.

## Keeping docs current

- A PR that changes behavior updates the docs that describe it in the same PR (search `docs/`, `AGENTS.md` and `.claude/skills/` for the names you changed).
- Periodic review: when `check_conventions.py` prints a stale-doc warning (the `next-task` skill lists them as candidates), review that doc as its own small PR:
  1. Read the whole doc. For each claim (paths, commands, parameter names, behavior), check it against the code or by running the command.
  2. Fix or delete what is wrong; move content that lives in the wrong place (see the table above).
  3. Set the date to today and say in the PR what was checked.
