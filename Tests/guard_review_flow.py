# レビューの流れを機械的に守らせる、Claude Code の PreToolUse フック(#195)。
#
#   python Tests/guard_review_flow.py --hook      stdin の JSON(Bash/PowerShell のコマンド)を読み、止めるときは
#                                                 stderr に理由を出して終了コード2(実行させない)
#   python Tests/guard_review_flow.py --whoami <transcript>   その会話をワーカーと判定するかを表示する(確認用)
#
# 止めるもの:
#   1. オーケストレーションのワーカーの会話での CodexReview.ps1 の -SetStatus(マージの予約はコーディネーターの役目)。
#      -Post は通す。
#   2. ./PrePr.ps1 のスタンプの sha が HEAD と違うときの gh pr create。
#
# guard_merge_approval.py と同じく、シェルの構文は解析しない(PR #161 の Codex レビューで、構文を追う正規表現は
# 指摘が続いた)。同じコマンドの文字列に CodexReview と -SetStatus があれば止める。commit のメッセージや PR の本文に
# 書くときは、-F や --body-file でファイルから渡せば止まらない。スクリプトのファイルを経由したものや splatting は
# 見えない。安全の境界ではなく、うっかり実行することを防ぐためのもの。
# 例外は orca orchestration のコマンドで、本文を --body-file で渡せないものがある(ask など)。そのため orca orchestration を
# 含むコマンドだけは、空白を含む引用符の中とヒアドキュメントの本文を除いて判定する(PR #196)。同じコマンドの本物の呼び出しは止まる。
# 空白を含む引用符のパスで呼ぶ CodexReview と orca orchestration を 1 つのコマンドに並べたものは見えない。
#
# ワーカーの見分け方: 会話の記録(transcript_path)の最初のユーザーメッセージが、Orca の worker-start の前書き
# 「You are a dispatched worker.」で始まること。環境変数では見分けられない。ORCA_TERMINAL_HANDLE は Orca の
# 構造化モードのワーカーでは structworker_... だが、PTY モードのワーカーはコーディネーターと同じ term_... になる
# (どちらのモードになるかはユーザーの設定で決まる)。読めないときや前書きがないときは止めない。
import json
import os
import re
import subprocess
import sys

STAMP_NAME = "loopbgm-prepr-stamp"

# 記録の中の最初のユーザーメッセージを探すときに読む上限。その前には数行のメタ情報しかない
_HEAD_BYTES = 1024 * 1024
_WORKER_PREAMBLE = "You are a dispatched worker."
_PREAMBLE_WINDOW = 200

_CODEX_REVIEW = re.compile(r"CodexReview(?:\.ps1)?(?![\w.-])", re.IGNORECASE)
# PowerShell は一意であれば引数名を省略できる(-SetS、-S など)ので、-SetStatus の前方一致を止める
_DASH_S = re.compile(r"(?<![\w-])-s[a-z]*", re.IGNORECASE)
_PR_CREATE = re.compile(
    r"(?<![\w.-])gh(?:\.exe)?(?:\s+(?:-R|--repo)[\s=]\S+)?\s+pr\s+create(?![\w-])", re.IGNORECASE
)
_ORCA_ORCHESTRATION = re.compile(r"(?<![\w.-])orca(?:\.exe)?\s+orchestration(?![\w-])", re.IGNORECASE)
# 左から順に、PowerShell のヒア文字列、シェルのヒアドキュメント、二重引用符、単一引用符を読み飛ばす
_QUOTED = re.compile(
    r"""@'.*?\n'@|@".*?\n"@|<<-?\s*['"]?(\w+)['"]?[^\n]*\n.*?\n\s*\1(?!\w)|"(?:[^"\\`]|[\\`].)*"|'(?:[^']|'')*'""",
    re.DOTALL,
)


def _without_message_bodies(command: str) -> str:
    """orca orchestration のコマンドなら、本文(空白を含む引用符の中とヒアドキュメント)を除く。"""
    def blank(match):
        if match.group(1):  # ヒアドキュメント: 1 行目はコマンドなので残す
            return match.group(0).split("\n", 1)[0]
        return match.group(0) if not re.search(r"\s", match.group(0)) else " "

    visible = _QUOTED.sub(blank, command)
    return visible if _ORCA_ORCHESTRATION.search(visible) else command


def runs_set_status(command: str) -> bool:
    """CodexReview と -SetStatus(省略形を含む)が同じコマンドにあれば True。"""
    command = _without_message_bodies(command)
    if not _CODEX_REVIEW.search(command):
        return False
    return any("-setstatus".startswith(match.group(0).lower()) for match in _DASH_S.finditer(command))


def creates_pr(command: str) -> bool:
    return _PR_CREATE.search(_without_message_bodies(command)) is not None


def _first_user_text(transcript_path: str) -> str:
    with open(transcript_path, "rb") as file:
        head = file.read(_HEAD_BYTES)
    for line in head.split(b"\n"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(b.get("text", "") for b in content if isinstance(b, dict))
        return ""
    return ""


def is_orchestration_worker(transcript_path) -> bool:
    """最初のユーザーメッセージが worker-start の前書きなら True。読めなければ False(止めない)。"""
    if not transcript_path:
        return False
    try:
        text = _first_user_text(transcript_path)
    except OSError:
        return False
    return _WORKER_PREAMBLE in text[:_PREAMBLE_WINDOW]


def _git(cwd, *args):
    try:
        # git はパスを UTF-8 で出す。既定のロケール(cp932)で読むと、日本語のパスで壊れる
        result = subprocess.run(["git", "-C", cwd, *args], capture_output=True, encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def stamp_is_current(cwd: str) -> bool:
    """スタンプの sha が HEAD と同じなら True。git のリポジトリでないなど、HEAD が分からなければ止めない。"""
    head = _git(cwd, "rev-parse", "HEAD")
    stamp_path = _git(cwd, "rev-parse", "--git-path", STAMP_NAME)
    if not head or not stamp_path:
        return True
    try:
        with open(os.path.join(cwd, stamp_path), encoding="utf-8") as file:
            return file.read().strip() == head
    except OSError:
        return False


SET_STATUS_MESSAGE = (
    "CodexReview.ps1 の -SetStatus は、コーディネーターだけが実行します(#195)。"
    "ワーカーは ./CodexReview.ps1 -Pr <N> -Post を実行し、指摘を直して PASS してから ask で「PR 準備完了」を送ってください。\n"
    "コミットのメッセージや本文に書いただけで止まったときは、-F や --body-file でファイルから渡してください。"
)
STAMP_MESSAGE = (
    "HEAD の ./PrePr.ps1 が通っていないので、gh pr create を止めました(#195)。"
    "./PrePr.ps1 を PowerShell で実行し、通してから PR を作ってください。\n"
    "スタンプでは自己点検の項目を読んだことまでは確かめられません。"
    "PrePr.ps1 が出す項目を確かめ、結果を PR 本文の「自己点検」の節に書いてください。"
)


def run_hook() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if runs_set_status(command) and is_orchestration_worker(payload.get("transcript_path")):
        print(SET_STATUS_MESSAGE, file=sys.stderr)
        return 2
    if creates_pr(command) and not stamp_is_current(payload.get("cwd") or os.getcwd()):
        print(STAMP_MESSAGE, file=sys.stderr)
        return 2
    return 0


def main(argv) -> int:
    if "--hook" in argv:
        return run_hook()
    if len(argv) == 2 and argv[0] == "--whoami":
        print("worker" if is_orchestration_worker(argv[1]) else "not a worker")
        return 0
    print("usage: guard_review_flow.py --hook | --whoami <transcript>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
