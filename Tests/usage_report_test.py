# Tests/usage_report.py の回帰テスト(#195)。%TEMP% の偽の記録を集計する。
#
#   python Tests/usage_report_test.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_report.py")


def assistant(message_id, timestamp, cache_read=100, output=5, tools=()):
    return {"type": "assistant", "timestamp": timestamp, "message": {
        "id": message_id,
        "usage": {"input_tokens": 1, "output_tokens": output, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": 2},
        "content": [{"type": "tool_use", "name": name} for name in tools]}}


def tool_result(timestamp):
    return {"type": "user", "timestamp": timestamp, "message": {"content": [
        {"type": "tool_result", "content": "abcd"},
        {"type": "tool_result", "content": [{"type": "text", "text": "xy"}, {"type": "image"}, {"type": "image"}]}]}}


class UsageReport(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="loopbgm_usage_test_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.write("F--loop-bgm", "aaaaaaaa-1", [
            assistant("m1", "2026-11-04T10:00:00Z", 100, 5, ["PowerShell"]),
            assistant("m1", "2026-11-04T10:00:00Z", 100, 5, ["Read"]),  # 同じ ID は 1 ターン
            tool_result("2026-11-04T10:00:01Z"),
            assistant("m2", "2026-11-04T11:00:00Z", 300, 7),
            assistant("m3", "2026-11-06T00:00:00Z", 1000, 1),
        ])
        self.write("C--orca-loop-bgm-issue-1", "bbbbbbbb-2", [assistant("m1", "2026-11-04T12:00:00Z", 50)])
        self.write("other-project", "cccccccc-3", [assistant("m1", "2026-11-04T12:00:00Z", 99999)])
        self.write(os.path.join("F--loop-bgm", "aaaaaaaa-1", "subagents"), "agent-x",
                   [assistant("s1", "2026-11-04T12:00:00Z", 7)])

    def write(self, folder, name, entries):
        path = os.path.join(self.root, folder)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, name + ".jsonl"), "w", encoding="utf-8") as file:
            file.write("not json\n[1]\n")
            for entry in entries:
                file.write(json.dumps(entry) + "\n")

    def report(self, *args):
        result = subprocess.run([sys.executable, SCRIPT, "--root", self.root, *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8")

    def report_json(self, *args):
        return json.loads(self.report("--json", *args))

    def test_period_and_counts(self):
        data = self.report_json("--since", "2026-11-01", "--until", "2026-11-05")
        self.assertEqual(data["session_count"], 3, "other projects are excluded; subagent logs are included")
        row = data["sessions"][0]
        self.assertEqual(row["session"], "aaaaaaaa-1")
        self.assertEqual(row["project"], "F--loop-bgm")
        self.assertEqual(row["turns"], 2)
        self.assertEqual(row["cache_read"], 400)
        self.assertEqual(row["cache_read_per_turn"], 200)
        self.assertEqual(row["output"], 12)
        self.assertEqual(row["images"], 2)
        self.assertEqual(row["tool_result_chars"], 6)
        self.assertEqual(row["tools"], {"PowerShell": 1, "Read": 1})
        self.assertEqual(data["total"]["turns"], 4)

    def test_last_usage_of_a_message_wins(self):
        # ストリーミングで同じ ID の行が続き、output_tokens が増える記録(PR #196 の Codex の指摘)
        self.write("streaming-loop-bgm", "dddddddd-4", [
            assistant("s1", "2026-11-04T10:00:00Z", 100, 1),
            assistant("s1", "2026-11-04T10:00:01Z", 100, 100),
            assistant("s2", "2026-11-04T10:00:02Z", 50, 3),
        ])
        row = self.report_json("--since", "2026-11-01", "--until", "2026-11-05", "--session", "dddddddd")["sessions"][0]
        self.assertEqual((row["turns"], row["output"], row["cache_read"]), (2, 103, 150))

    def test_until_excludes_and_since_includes(self):
        data = self.report_json("--since", "2026-11-05", "--session", "aaaaaaaa")
        self.assertEqual([r["turns"] for r in data["sessions"]], [1])
        self.assertEqual(data["sessions"][0]["cache_read"], 1000)

    def test_project_filter(self):
        data = self.report_json("--since", "2026-11-01", "--until", "2026-11-05", "--project", "other")
        self.assertEqual([r["cache_read"] for r in data["sessions"]], [99999])

    def test_top_limits_rows_but_not_the_total(self):
        data = self.report_json("--since", "2026-11-01", "--until", "2026-11-05", "--top", "1")
        self.assertEqual(len(data["sessions"]), 1)
        self.assertEqual(data["total"]["turns"], 4)

    def test_text_output(self):
        text = self.report("--since", "2026-11-01", "--until", "2026-11-05")
        self.assertIn("TOTAL 3 会話", text)
        self.assertIn("aaaaaaaa", text)

    def test_empty_period(self):
        self.assertIn("TOTAL 0 会話", self.report("--since", "2030-01-01"))

    def test_does_not_write(self):
        before = sorted(os.path.join(d, f) for d, _, files in os.walk(self.root) for f in files)
        self.report("--since", "2026-11-01")
        self.assertEqual(before, sorted(os.path.join(d, f) for d, _, files in os.walk(self.root) for f in files))


if __name__ == "__main__":
    unittest.main()
