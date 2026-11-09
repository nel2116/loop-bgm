# 会話の文脈が大きくなったら、新しい会話への引き継ぎを促す、Claude Code の PostToolUse フック(#195、#256)。
#
#   python Tests/context_size_warning.py --hook   stdin の JSON の transcript_path を読み、超えていれば
#                                                 additionalContext で警告する。止めることはない(終了コードは常に 0)
#
# 消費は「ターン数 × その時点の文脈の大きさ」で増える(#195 の集計では、1 ターンあたり約 22 万トークン)。
# 文脈の大きさは、最後のアシスタントのメッセージの usage(input + cache_read + cache_creation)で測る。
# ツールの呼び出しごとに動くので、記録の末尾だけを読む。末尾に usage が見つからないときは何もしない
# (巨大な画像の行など。次の呼び出しで見つかる)。
#
# しきい値は環境変数 LOOPBGM_CONTEXT_WARN_TOKENS(既定 120000、0 以下で無効)。そこから
# LOOPBGM_CONTEXT_WARN_STEP(既定 50000、0 以下なら 1 回だけ)増えるごとに、もう一度警告する。
# 1 回きりの警告では見送られたあと何百ターンも続いた(#256 の集計で、15 万を超えたあとのターンが cache_read の約 65%)。
# 警告した段階ごとに %TEMP%\loopbgm-context-warning\<session_id>-<段階> の印を排他的に作る(並列のツール呼び出しで
# 同じ段階を 2 回警告しないため)。#195 の印 <session_id> は 1 段階目とみなす。印を作れないときは、同じ警告を毎回出さないよう、
# 警告しない。
import json
import os
import re
import sys
import tempfile

DEFAULT_THRESHOLD = 120000
DEFAULT_STEP = 50000
_TAIL_BYTES = 256 * 1024


def _int_from_env(name, default) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def threshold_from_env() -> int:
    return _int_from_env("LOOPBGM_CONTEXT_WARN_TOKENS", DEFAULT_THRESHOLD)


def step_from_env() -> int:
    return _int_from_env("LOOPBGM_CONTEXT_WARN_STEP", DEFAULT_STEP)


def stage_of(tokens, limit, step) -> int:
    """しきい値以下なら 0。超えたら 1 で、そこから step 増えるごとに 1 つ上がる。step が 0 以下なら 1 で止まる。"""
    if tokens <= limit:
        return 0
    if step <= 0:
        return 1
    return (tokens - limit - 1) // step + 1


def last_context_tokens(transcript_path):
    """記録の末尾から、最後のアシスタントのメッセージの文脈の大きさを返す。見つからなければ None。"""
    try:
        with open(transcript_path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - _TAIL_BYTES))
            tail = file.read()
    except (OSError, TypeError):
        return None
    lines = tail.split(b"\n")
    if size > _TAIL_BYTES:
        lines = lines[1:]  # 先頭の行は途中から読んでいる
    for line in reversed(lines):
        if b'"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        total = sum(usage.get(key) or 0 for key in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        # API を呼ばずに作られたメッセージ(usage がすべて 0)は測定値ではない
        if total > 0:
            return total
    return None


def _highest_warned(folder, name) -> int:
    """この会話で警告済みの最も高い段階。印がなければ 0。"""
    try:
        entries = os.listdir(folder)
    except OSError:
        return 0
    highest = 0
    for entry in entries:
        if entry == name:
            highest = max(highest, 1)  # #195 の印
        elif entry.startswith(name + "-") and entry[len(name) + 1:].isdigit():
            highest = max(highest, int(entry[len(name) + 1:]))
    return highest


def mark_warned(session_id, stage) -> bool:
    """この会話でこの段階より上をまだ警告していなければ、段階の印を排他的に作って True を返す。
    警告済み、ほかの呼び出しが先に作った、または作れなければ False。"""
    name = re.sub(r"[^\w.-]", "_", str(session_id or "unknown"))
    folder = os.path.join(tempfile.gettempdir(), "loopbgm-context-warning")
    if stage <= _highest_warned(folder, name):
        return False
    try:
        os.makedirs(folder, exist_ok=True)
        os.close(os.open(os.path.join(folder, f"{name}-{stage}"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return False
    return True


def run_hook() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
    except ValueError:
        return 0
    limit = threshold_from_env()
    if not isinstance(payload, dict) or limit <= 0:
        return 0
    tokens = last_context_tokens(payload.get("transcript_path"))
    if tokens is None:
        return 0
    step = step_from_env()
    stage = stage_of(tokens, limit, step)
    if stage == 0 or not mark_warned(payload.get("session_id"), stage):
        return 0
    message = (
        f"この会話の文脈が約 {tokens:,} トークンになりました(しきい値 {limit:,}、{stage} 回目の警告)。"
        "消費は「ターン数 × 文脈の大きさ」で増え、この先のターンはすべてこの大きさで読み直されます。"
        "いまの作業の区切りで新しい会話に引き継いでください。"
        "ワーカーは、コミットして push し、残りの作業と確かめたことを書き出して、ask でコーディネーターに引き継ぎを頼む。"
        "コーディネーターやふつうの会話は、Issue・PR の状態と残りの作業を書き出して、ユーザーに /clear と再開を頼む。"
    )
    if step > 0:
        message += f"文脈がさらに {step:,} トークン増えるごとに、この警告をもう一度出します(#256)。"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--hook" in sys.argv[1:]:
        sys.exit(run_hook())
    print("usage: context_size_warning.py --hook", file=sys.stderr)
    sys.exit(2)
