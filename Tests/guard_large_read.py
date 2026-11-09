# 大きなテキストファイルを範囲指定なしで丸ごと Read するのを止める、Claude Code の PreToolUse フック(#256)。
#
#   python Tests/guard_large_read.py --hook      stdin の JSON(Read の file_path、offset、limit)を読み、止めるときは
#                                                stderr に理由を出して終了コード2(実行させない)
#
# Read した中身は文脈に残り、以降の毎ターン読み直される(#256 の集計で、丸ごとの Read がツール出力の 1 位)。
# 必要な場所を grep -n で探してから、offset/limit で範囲を読んでもらう。
#
# 止める条件:
#   1. offset も limit もない。どちらかがあれば、範囲を考えて読んでいるので通す(全体が本当に必要なときの逃げ道でもある)。
#   2. 会話の記録(.jsonl)である。大きさに関係なく止める。集計は Tests/usage_report.py で行う。
#   3. テキストファイルで、MAX_BYTES バイトか MAX_LINES 行を超える。画像、PDF、ノートブックは Read が別に扱うので対象外。
# ファイルが読めないときは止めない(Read 自身のエラーに任せる)。
import json
import os
import sys

MAX_BYTES = 30 * 1024
MAX_LINES = 600
_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".pdf", ".ipynb"}


def _count_lines(path, limit):
    """limit 行を超えたら途中でやめる。読めなければ None。"""
    count = 0
    try:
        with open(path, "rb") as file:
            for _ in file:
                count += 1
                if count > limit:
                    break
    except OSError:
        return None
    return count


def block_reason(tool_input):
    """止める理由を返す。通すなら None。"""
    if not isinstance(tool_input, dict):
        return None
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return None
    path = tool_input.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    extension = os.path.splitext(path)[1].lower()
    if extension == ".jsonl":
        return (
            "会話の記録(.jsonl)は丸ごと読みません(#256。1 回で数万文字になり、毎ターン読み直されます)。"
            "消費の集計は python Tests/usage_report.py を使い、中身は grep や tail で必要な行だけを取り出してください。"
        )
    if extension in _BINARY_EXTENSIONS:
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > MAX_BYTES:
        shown = f"{size:,} バイト"  # 行は数えない(改行のない巨大なファイルを 1 行として読み込まないため)
    else:
        lines = _count_lines(path, MAX_LINES)
        if lines is None or lines <= MAX_LINES:
            return None
        shown = f"{MAX_LINES} 行超"
    return (
        f"{path} は大きい({shown})ので、範囲指定なしでは読みません(#256。読んだ中身は以降の毎ターン読み直されます)。"
        "grep -n で必要な場所(関数名、見出しなど)を探し、Read の offset と limit でその範囲だけを読んでください。"
        "全体が本当に必要なときは、limit を明示して読んでください。"
    )


def run_hook() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    reason = block_reason(payload.get("tool_input"))
    if reason is None:
        return 0
    print(reason, file=sys.stderr)
    return 2


def main(argv) -> int:
    if "--hook" in argv:
        return run_hook()
    print("usage: guard_large_read.py --hook", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
