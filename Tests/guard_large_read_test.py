# Tests/guard_large_read.py の回帰テスト(#256)。
#
#   python Tests/guard_large_read_test.py
#
# フック(--hook)は、Claude Code と同じく stdin に JSON を渡して別プロセスとして確かめる。
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_large_read as guard  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_large_read.py")


class GuardLargeRead(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="loopbgm_large_read_test_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def make(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        return path

    def run_hook(self, tool_input):
        data = json.dumps({"tool_name": "Read", "tool_input": tool_input}).encode()
        return subprocess.run([sys.executable, SCRIPT, "--hook"], input=data, capture_output=True)

    def test_small_file_passes(self):
        path = self.make("small.cpp", "int a;\n" * 100)
        self.assertIsNone(guard.block_reason({"file_path": path}))

    def test_many_lines_are_blocked(self):
        path = self.make("long.cpp", "x\n" * (guard.MAX_LINES + 1))
        self.assertIn("600 行超", guard.block_reason({"file_path": path}))
        path = self.make("edge.cpp", "x\n" * guard.MAX_LINES)
        self.assertIsNone(guard.block_reason({"file_path": path}), "exactly MAX_LINES lines")

    def test_large_bytes_are_blocked(self):
        path = self.make("wide.md", ("y" * 200 + "\n") * 160)  # 160 行、約 32KB
        self.assertIn("バイト", guard.block_reason({"file_path": path}))

    def test_large_file_is_blocked_without_counting_lines(self):
        path = self.make("one_line.json", "z" * (guard.MAX_BYTES + 1))
        original = guard._count_lines
        guard._count_lines = lambda *_: self.fail("lines must not be counted")
        try:
            self.assertIn("バイト", guard.block_reason({"file_path": path}))
        finally:
            guard._count_lines = original

    def test_range_passes(self):
        path = self.make("long.cpp", "x\n" * 5000)
        self.assertIsNone(guard.block_reason({"file_path": path, "offset": 100}))
        self.assertIsNone(guard.block_reason({"file_path": path, "limit": 50}))
        self.assertIsNone(guard.block_reason({"file_path": path, "offset": 0, "limit": 5000}))

    def test_transcript_is_blocked_at_any_size(self):
        path = self.make("session.jsonl", "{}\n")
        self.assertIn("usage_report", guard.block_reason({"file_path": path}))
        self.assertIsNone(guard.block_reason({"file_path": path, "offset": 1, "limit": 20}))

    def test_binary_and_missing_files_pass(self):
        path = self.make("big.png", "z" * (guard.MAX_BYTES + 1))
        self.assertIsNone(guard.block_reason({"file_path": path}))
        self.assertIsNone(guard.block_reason({"file_path": os.path.join(self.dir, "missing.cpp")}))
        for broken in [None, "text", {}, {"file_path": ""}, {"file_path": 3}]:
            self.assertIsNone(guard.block_reason(broken))

    def test_hook_exit_codes(self):
        long_path = self.make("long.cpp", "x\n" * 5000)
        blocked = self.run_hook({"file_path": long_path})
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("offset", blocked.stderr.decode("utf-8"))
        self.assertEqual(self.run_hook({"file_path": long_path, "limit": 10}).returncode, 0)
        for payload in [b"not json", b"[1]", b"{}"]:
            result = subprocess.run([sys.executable, SCRIPT, "--hook"], input=payload, capture_output=True)
            self.assertEqual((result.returncode, result.stderr), (0, b""))


if __name__ == "__main__":
    unittest.main()
