---
name: create-issue
description: Create a loop-bgm GitHub issue in this repository's style (Japanese, sections 現象/原因/対応案/完了条件, verified facts kept apart from guesses). Use when turning a problem found during work or a GUI check into an issue, when the user says 「Issue にして」「Issue を立てて」, or when adding verification results to an existing issue.
---

# Creating an issue

<!-- last-reviewed: 2026-10-27 -->

Turn a problem found during work into an issue that someone else (or Claude in another session) can reproduce, fix and judge as done. The issue itself is written in Japanese.

## 1. Look for duplicates

```bash
gh issue list --state all --limit 60 --json number,title,state --jq '.[]|[.number,.state,.title]|@tsv'
gh issue list --state all --search "<keyword>" --json number,title,state
```

- If an open issue covers the same problem, do not create a new one. Add what you found as a comment (`gh issue comment <N> --body-file <file>`). Always add it when you verified a point that issue marks as 「GUIでは未確認」 or 「推測」.
- If it matches a closed issue, create a new one as a recurrence and reference the old issue in the body.

## 2. Confirm the cause in the code

- Don't describe only the symptom. Read the related code and point at the cause as `file:line` or a function name.
- **Keep verified facts apart from guesses.** What actually happened (logs, dialogs, exit codes) is stated as fact. A cause inferred from reading code gets 「(コードからの推測)」/「(推定)」 in the heading, or 「(未確認)」 after the sentence.
- When you reproduced it, write the date (`YYYY/MM/DD`, absolute), the work it happened during (e.g. 「PR #114 の GUI 確認」) and the data used. Paste errors and logs verbatim in code blocks.
- If your explanation changed along the way (e.g. first "happens in a new worktree", actually "when develop is merged into an existing worktree"), write the verified version.

## 3. Write the body

Write the body as a file in the scratchpad with the Write tool. Passing it through a heredoc or `--body "..."` drops the backslashes in Windows paths (see "Write edit scripts to a file" in CLAUDE.md).

Use these four headings (as in #104, #107, #111, #116-#118):

```markdown
## 現象
何をすると、何が起きるか。期待との違い。実際に起きたときの日付・状況と、ログやエラーの原文。

## 原因
コードの箇所を挙げて、なぜ起きるか。推測の部分は明示する。

## 対応案
直し方の候補。最低限の対応と、さらに望ましい対応があれば分ける。ユーザー環境変数などの外部の状態を勝手に変えない案を優先する。

## 完了条件
直ったと判定できる、確かめられる条件。GUI でしか確かめられないものには「(GUIで確認)」と付ける。自動テストで確かめられるものは、そのテスト(`EngineUnitTests`、`Tests/*.ps1`、CI)を書く。
```

- Add notes to a heading in parentheses (e.g. `## 原因(2 はコードからの推測)`).
- Reference related issues/PRs as `#N`, and say which work the problem was found in (e.g. 「#10(PR #108)の作業中にワーカーが見つけた」).
- Plain だ・である style, not the polite style used for reports to the user.

## 4. Title

- Japanese, one sentence saying **what happens**. If the location of the cause is known, it may start with a function or file name (e.g. 「`Restore.ps1`が…を検出せず、…が NETSDK1004 で失敗する」).
- No prefix such as `[bug]`.
- Normally no labels (recent issues have none). If you add one, use only existing labels (`bug`, `enhancement`, `chore`, `test`, `documentation`); never create labels. `hold` blocks PRs and is not for issues.

## 5. Create it

```bash
gh issue create --title "<title>" --body-file "<scratchpad>/issue_<name>.md"
```

- One issue per problem; don't bundle several.
- Reflect the new issue number in related memory files (`memory/`) and docs.

## 6. Report to the user

In Japanese, list links to the issues created and commented on. For each, mention any point still left as a guess (not yet verified).
