# エージェントが PR に merge-ok ラベルを付けるのを止める、Claude Code の PreToolUse フック(#160)。
#
#   python Tests/guard_merge_approval.py --hook      stdin の JSON(Bash/PowerShell のコマンド)を読み、merge-ok を
#                                                    付けるコマンドなら stderr に理由を出して終了コード2(実行させない)
#   python Tests/guard_merge_approval.py "<command>" コマンドを判定して結果を表示する(確認用)
#
# merge-ok は、人がマージを承認するラベルである(.github/workflows/pr-automation.yml の Merge approved)。
# エージェントはユーザーと同じ GitHub アカウント(gh)で動くので、GitHub の側では人とエージェントを区別できない。
# そのため、エージェントが付けられないようにここで止める。止めるのは gh のコマンドだけで、スクリプトのファイルを
# 経由したものや curl などは見ない(安全の境界ではなく、うっかり付けることを防ぐためのもの)。
import json
import re
import sys

LABEL = "merge-ok"

# シェルの構文(グローバルオプション、行の継続、引用符の中の本文)は解析しない。正規表現で構文を追う方式は
# 見落としと誤検出の指摘が続く(#124、PR #161 の Codex レビュー)。そのため、gh と merge-ok が同じコマンドに
# あれば、読み取りのコマンドも含めて止める。ラベルの確認は --json labels で行い、本文は --body-file で渡せば、
# コマンドに merge-ok を書かずに済む。
# Windows はコマンド名(GH.EXE)の、GitHub はラベル名(MERGE-OK)の大文字と小文字を区別しない
_GH = re.compile(r"(?<![\w.-])gh(?:\.exe)?(?![\w.-])", re.IGNORECASE)


def adds_merge_ok(command: str) -> bool:
    """gh を呼ぶコマンドに merge-ok が含まれていれば True(付けるかどうかは区別しない)。"""
    return LABEL in command.lower() and _GH.search(command) is not None


MESSAGE = (
    "merge-ok は、人がマージを承認するためのラベルです。エージェントは付けません(#160)。\n"
    "マージの準備ができたら、承認待ちであることを PR の番号とともにユーザーに報告してください。\n"
    "gh のコマンドに merge-ok を書くと、読み取りでも止めます。ラベルは --json labels で確かめ、"
    "本文やコメントは --body-file で渡してください。"
)


def run_hook() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except ValueError:
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if adds_merge_ok(command):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


def main(argv) -> int:
    if "--hook" in argv:
        return run_hook()
    for command in argv:
        print(f"{'BLOCK' if adds_merge_ok(command) else 'allow'}: {command}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
