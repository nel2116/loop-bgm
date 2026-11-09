# リポジトリの規約を確かめる(DXForgeEX の同名スクリプトを loop-bgm 向けに作り直したもの)。
#
#   python Tests/check_conventions.py                  追跡中のファイルをすべて確かめる(CI と PrePr.ps1)
#   python Tests/check_conventions.py <file>...        指定したファイルだけ確かめる
#   python Tests/check_conventions.py --fix <file>...  BOM の有無を直す
#   python Tests/check_conventions.py --hook           Claude Code の PostToolUse フック。stdin の JSON から
#                                                      編集されたファイルを読み、違反があれば stderr に出して終了コード 2
#
# 規則:
#   bom      .ps1 は UTF-8 の BOM 付き(Windows PowerShell 5.1 が日本語を読み違えないため)。それ以外のテキストは BOM なし。
#   review   追跡中の .md には `<!-- last-reviewed: YYYY-MM-DD -->` の行がちょうど 1 つ(書式は writing-docs スキル)。
#            未来の日付は違反、90 日より古いものは警告。
#   audio    音声ファイルを追跡しない(公開リポジトリに音源や書き出しを載せないため。docs/spec.md 11.1)。
#   json     songs/ と templates/ の .json は読める JSON であること。
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = b"\xef\xbb\xbf"
TEXT_EXT = {".py", ".ps1", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".html", ".js", ".css"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a"}
REVIEW_RE = re.compile(r"^<!-- last-reviewed: (\d{4}-\d{2}-\d{2}) -->$")
REVIEW_ANY = re.compile(r"^\s*<!--\s*last-reviewed")
STALE_DAYS = 90


def tracked_files():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def check_file(rel, today=None):
    """Return (violations, warnings) as lists of (rel, line, rule, message)."""
    today = today or datetime.date.today()
    errors, warnings = [], []
    path = os.path.join(ROOT, rel)
    ext = os.path.splitext(rel)[1].lower()
    if ext in AUDIO_EXT:
        errors.append((rel, 1, "audio", "音声ファイルはコミットしない(.gitignore と docs/spec.md 11.1)"))
        return errors, warnings
    if ext not in TEXT_EXT or not os.path.isfile(path):
        return errors, warnings
    with open(path, "rb") as file:
        data = file.read()
    has_bom = data.startswith(BOM)
    if ext == ".ps1" and not has_bom:
        errors.append((rel, 1, "bom", ".ps1 は BOM 付きの UTF-8 にする(--fix で直る)"))
    if ext != ".ps1" and has_bom:
        errors.append((rel, 1, "bom", "BOM を付けない(--fix で直る)"))
    text = data[len(BOM):].decode("utf-8", errors="replace") if has_bom else data.decode("utf-8", errors="replace")
    if ext == ".md":
        lines = text.splitlines()
        hits = [(i + 1, line) for i, line in enumerate(lines) if REVIEW_ANY.match(line)]
        if not hits:
            errors.append((rel, 1, "review", "`<!-- last-reviewed: YYYY-MM-DD -->` の行がない(writing-docs スキル)"))
        elif len(hits) > 1:
            errors.append((rel, hits[1][0], "review", "last-reviewed の行が 2 つ以上ある"))
        else:
            ln, line = hits[0]
            m = REVIEW_RE.match(line.strip())
            if not m:
                errors.append((rel, ln, "review", "last-reviewed の書式が違う(`<!-- last-reviewed: YYYY-MM-DD -->`)"))
            else:
                try:
                    day = datetime.date.fromisoformat(m.group(1))
                except ValueError:
                    errors.append((rel, ln, "review", "last-reviewed の日付が読めない"))
                else:
                    if day > today:
                        errors.append((rel, ln, "review", "last-reviewed が未来の日付"))
                    elif (today - day).days > STALE_DAYS:
                        warnings.append((rel, ln, "review", f"{STALE_DAYS} 日以上見直されていない(writing-docs スキル)"))
    if ext == ".json" and rel.replace("\\", "/").split("/")[0] in ("songs", "templates"):
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            errors.append((rel, e.lineno, "json", f"JSON として読めない: {e.msg}"))
    return errors, warnings


def fix_file(rel):
    path = os.path.join(ROOT, rel)
    with open(path, "rb") as file:
        data = file.read()
    want_bom = rel.lower().endswith(".ps1")
    if want_bom and not data.startswith(BOM):
        data = BOM + data
    elif not want_bom and data.startswith(BOM):
        data = data[len(BOM):]
    else:
        return
    with open(path, "wb") as file:
        file.write(data)


def relpath(p):
    try:
        return os.path.relpath(os.path.abspath(p), ROOT).replace("\\", "/")
    except ValueError:  # another drive on Windows: outside the repository
        return "../" + os.path.basename(p)


def run_hook():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    rel = relpath(path)
    if rel.startswith(".."):
        return 0
    errors, _ = check_file(rel)
    for r, ln, rule, msg in errors:
        print(f"{r}:{ln}: [{rule}] {msg}", file=sys.stderr)
    return 2 if errors else 0


def main(argv):
    if "--hook" in argv:
        return run_hook()
    fix = "--fix" in argv
    files = [a for a in argv if not a.startswith("--")]
    if fix:
        for f in files:
            fix_file(relpath(f))
    targets = [relpath(f) for f in files] if files else tracked_files()
    count = 0
    for rel in targets:
        errors, warnings = check_file(rel)
        for r, ln, rule, msg in warnings:
            print(f"warning: {r}:{ln}: [{rule}] {msg}")
        for r, ln, rule, msg in errors:
            print(f"{r}:{ln}: [{rule}] {msg}", file=sys.stderr)
            count += 1
    if count:
        print(f"{count} 件の規約違反があります。", file=sys.stderr)
        return 1
    print(f"規約違反はありません({len(targets)} ファイル)。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
