# Tests/guard_merge_approval.py の回帰テスト(#160)。
#
#   python Tests/guard_merge_approval_test.py
#
# merge-ok を付けるコマンドを止めることと、ほかのコマンド(外す、一覧で絞る、文字列を含むだけ)を止めないことの
# 両方を確かめる。フック(--hook)は、Claude Code と同じく stdin に JSON を渡して別プロセスとして確かめる。
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_merge_approval as guard  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_merge_approval.py")


class AddsMergeOk(unittest.TestCase):
    def test_blocks_commands_that_add_the_label(self):
        for command in [
            "gh pr edit 158 --add-label merge-ok",
            'gh pr edit 158 --add-label "hold,merge-ok"',
            "gh pr edit 158 --add-label=merge-ok",
            "gh issue edit 158 --add-label merge-ok",
            "gh pr create --base develop --title t --body b --label merge-ok",
            "gh pr create -l merge-ok -t t -b b",
            "gh.exe pr edit 158 --add-label merge-ok",
            "& gh pr edit 158 --add-label merge-ok",
            'gh api repos/{owner}/{repo}/issues/158/labels -f "labels[]=merge-ok"',
            "gh api -X POST repos/nel2116/loop-bgm/issues/158/labels -f labels[]=merge-ok",
            "git fetch origin; gh pr edit 158 --add-label merge-ok",
            "cd x && gh pr edit 158 --add-label merge-ok && echo done",
            "Set-Location x\ngh pr edit 158 --add-label merge-ok",
            # PR #161 の Codex の指摘: グローバルオプションと行の継続
            "gh --repo nel2116/loop-bgm pr edit 161 --add-label merge-ok",
            "gh pr edit 161 \\\n  --add-label merge-ok",
            "gh pr edit 161 `\n  --add-label merge-ok",
            # PR #161 の Codex の指摘: Windows ではコマンド名の大文字と小文字を区別しない。ラベル名も GitHub では同じ
            "GH.EXE pr edit 161 --add-label merge-ok",
            "Gh pr edit 161 --add-label merge-ok",
            "gh pr edit 161 --add-label MERGE-OK",
            # 構文を解析しないので、読み取りや本文の中の文字列でも止める(意図した割り切り)
            "gh pr view 158 --json labels | grep merge-ok",
            "gh pr edit 161 --body '承認は --add-label merge-ok で行う'",
            "gh label create merge-ok --color 0E8A16",
        ]:
            with self.subTest(command=command):
                self.assertTrue(guard.adds_merge_ok(command))

    def test_allows_other_commands(self):
        for command in [
            "gh pr edit 158 --add-label hold",
            "gh pr view 158 --json labels --jq '.labels[].name'",
            "gh pr edit 161 --body-file C:/tmp/body.md",
            'git commit -m "[fix] merge-ok を人が付ける (#160)"',
            "python Tests/guard_merge_approval.py --help-merge-ok",
            "grep -n merge-ok .github/workflows/pr-automation.yml",
            "gh pr checks 158",
            "./CodexReview.ps1 -Pr 158 -Post -SetStatus",
        ]:
            with self.subTest(command=command):
                self.assertFalse(guard.adds_merge_ok(command))


class Hook(unittest.TestCase):
    def run_hook(self, tool_name, command):
        payload = {"tool_name": tool_name, "tool_input": {"command": command}}
        return subprocess.run(
            [sys.executable, SCRIPT, "--hook"],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
        )

    def test_blocks_with_exit_code_2_and_a_reason(self):
        for tool_name in ["Bash", "PowerShell"]:
            with self.subTest(tool_name=tool_name):
                result = self.run_hook(tool_name, "gh pr edit 158 --add-label merge-ok")
                self.assertEqual(result.returncode, 2)
                self.assertIn("#160", result.stderr.decode("utf-8"))

    def test_allows_other_commands_silently(self):
        result = self.run_hook("Bash", "gh pr checks 158")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")

    def test_ignores_input_that_is_not_json(self):
        result = subprocess.run([sys.executable, SCRIPT, "--hook"], input=b"not json", capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
