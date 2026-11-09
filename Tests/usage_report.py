# ローカルの Claude Code のセッションの記録から、会話ごとのトークン消費を集計する(#195)。読むだけで、何も書かない。
#
#   python Tests/usage_report.py                                  直近 7 日、loop-bgm の会話(合計の多い順に 15 件)
#   python Tests/usage_report.py --since 2026-11-04 --until 2026-11-05
#   python Tests/usage_report.py --project issue-185 --project F--HAL --top 30
#   python Tests/usage_report.py --session 15175afe --json
#
# 期間は各ターンの timestamp(UTC)で判定する。記録は ~/.claude/projects/<プロジェクト>/*.jsonl と、その下の
# サブエージェントの記録。同じメッセージの ID は 1 ターンとして数え、最後の行の usage を使う
# (ストリーミングで複数の行になり、後の行で output_tokens が増えることがあるため)。
import argparse
import collections
import datetime
import glob
import json
import os
import sys

DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
UTC = datetime.timezone.utc


def parse_date(text: str) -> datetime.datetime:
    value = datetime.datetime.fromisoformat(text)
    return value.astimezone(UTC) if value.tzinfo is None else value


def _timestamp(entry):
    text = entry.get("timestamp")
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_file(path, since=None, until=None):
    """1 つの記録を集計する。期間内のターンがなければ None。"""
    row = collections.Counter()
    tools = collections.Counter()
    usages = {}
    with open(path, encoding="utf-8", errors="replace") as file:
        for line in file:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            when = _timestamp(entry)
            if when is not None and ((since and when < since) or (until and when >= until)):
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            blocks = content if isinstance(content, list) else []
            if entry.get("type") == "assistant":
                usage = message.get("usage") if isinstance(message, dict) else None
                message_id = message.get("id") if isinstance(message, dict) else None
                if usage:
                    usages[message_id if message_id is not None else object()] = usage
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tools[block.get("name")] += 1
            elif entry.get("type") == "user":
                for block in blocks:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    result = block.get("content")
                    if isinstance(result, str):
                        row["tool_result_chars"] += len(result)
                    elif isinstance(result, list):
                        for item in result:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "text":
                                row["tool_result_chars"] += len(item.get("text") or "")
                            elif item.get("type") == "image":
                                row["images"] += 1
    if not usages:
        return None
    for usage in usages.values():
        row["turns"] += 1
        row["input"] += usage.get("input_tokens") or 0
        row["output"] += usage.get("output_tokens") or 0
        row["cache_read"] += usage.get("cache_read_input_tokens") or 0
        row["cache_write"] += usage.get("cache_creation_input_tokens") or 0
    return {
        "project": os.path.basename(os.path.dirname(path)),
        "session": os.path.splitext(os.path.basename(path))[0],
        "turns": row["turns"],
        "input": row["input"],
        "cache_read": row["cache_read"],
        "cache_read_per_turn": row["cache_read"] // row["turns"],
        "cache_write": row["cache_write"],
        "output": row["output"],
        "images": row["images"],
        "tool_result_chars": row["tool_result_chars"],
        "tools": dict(tools.most_common(4)),
    }


def collect(root, projects, sessions, since, until):
    rows = []
    for folder in sorted(glob.glob(os.path.join(glob.escape(root), "*"))):
        if projects and not any(name in os.path.basename(folder) for name in projects):
            continue
        for path in glob.glob(os.path.join(glob.escape(folder), "**", "*.jsonl"), recursive=True):
            if sessions and not any(name in os.path.basename(path) for name in sessions):
                continue
            if since and datetime.datetime.fromtimestamp(os.path.getmtime(path), UTC) < since:
                continue
            try:
                row = summarize_file(path, since, until)
            except OSError as error:
                print(f"読めません: {path}: {error}", file=sys.stderr)
                continue
            if row:
                row["project"] = os.path.basename(folder)
                rows.append(row)
    rows.sort(key=lambda r: -(r["cache_read"] + r["cache_write"]))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="会話ごとのトークン消費を集計する(読むだけ)")
    parser.add_argument("--since", type=parse_date, help="この日時以降(YYYY-MM-DD[THH:MM])。既定は 7 日前")
    parser.add_argument("--until", type=parse_date, help="この日時より前")
    parser.add_argument("--project", action="append", help="プロジェクトのフォルダ名に含まれる文字列(複数可)。既定は loop-bgm")
    parser.add_argument("--session", action="append", help="記録のファイル名に含まれる文字列(複数可)")
    parser.add_argument("--top", type=int, default=15, help="表示する会話の数(既定 15)")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="記録のフォルダ(既定 ~/.claude/projects)")
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)

    since = args.since or datetime.datetime.now(UTC) - datetime.timedelta(days=7)
    rows = collect(args.root, args.project or ["loop-bgm"], args.session, since, args.until)
    total = {key: sum(r[key] for r in rows) for key in
             ("turns", "input", "cache_read", "cache_write", "output", "images", "tool_result_chars")}
    total["cache_read_per_turn"] = total["cache_read"] // total["turns"] if total["turns"] else 0
    if args.json:
        print(json.dumps({"sessions": rows[:args.top], "total": total, "session_count": len(rows)}, ensure_ascii=False, indent=1))
        return 0

    print(f"{'turns':>6} {'cache_read':>12} {'per_turn':>9} {'cache_write':>11} {'output':>9} {'images':>6} "
          f"{'tool_chars':>10}  project / session / tools")
    for r in rows[:args.top]:
        print(f"{r['turns']:>6} {r['cache_read']:>12,} {r['cache_read_per_turn']:>9,} {r['cache_write']:>11,} "
              f"{r['output']:>9,} {r['images']:>6} {r['tool_result_chars']:>10,}  "
              f"{r['project'][-40:]} {r['session'][:8]} {r['tools']}")
    print(f"TOTAL {len(rows)} 会話: turns {total['turns']:,} cache_read {total['cache_read']:,} "
          f"(1 ターンあたり {total['cache_read_per_turn']:,}) cache_write {total['cache_write']:,} "
          f"output {total['output']:,} images {total['images']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
