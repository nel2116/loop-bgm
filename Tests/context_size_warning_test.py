# Tests/context_size_warning.py の回帰テスト(#195、#256)。
#
#   python Tests/context_size_warning_test.py
#
# 印は TEMP を差し替えた %TEMP% の使い捨てのフォルダに作る。
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_size_warning as warning  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context_size_warning.py")


def assistant(input_tokens=0, cache_read=0, cache_creation=0, **extra):
    return {"type": "assistant", "message": {"usage": {
        "input_tokens": input_tokens, "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation}}, **extra}


class TempDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="loopbgm_context_test_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "t.jsonl")

    def write(self, *entries):
        with open(self.path, "w", encoding="utf-8") as file:
            for entry in entries:
                file.write((entry if isinstance(entry, str) else json.dumps(entry)) + "\n")


class LastContextTokens(TempDir):
    def test_sums_the_last_assistant_usage(self):
        self.write(assistant(1, 1, 1), assistant(10, 200, 3000), {"type": "user", "message": {"content": "x"}})
        self.assertEqual(warning.last_context_tokens(self.path), 3210)

    def test_skips_sidechain_and_zero_usage_and_broken_lines(self):
        self.write(assistant(5), {"type": "assistant", "message": "text"}, assistant(9000, isSidechain=True),
                   assistant(0), '{"type":"assistant", broken')
        self.assertEqual(warning.last_context_tokens(self.path), 5)

    def test_no_usage(self):
        self.write({"type": "user", "message": {"content": "x"}})
        self.assertIsNone(warning.last_context_tokens(self.path))
        self.assertIsNone(warning.last_context_tokens(os.path.join(self.dir, "missing.jsonl")))
        self.assertIsNone(warning.last_context_tokens(None))

    def test_reads_only_the_tail(self):
        # 先頭の大きな値は読まれず、途中で切れた行でも壊れない
        self.write(assistant(999), {"type": "user", "pad": "x" * (warning._TAIL_BYTES + 10)}, assistant(7))
        self.assertEqual(warning.last_context_tokens(self.path), 7)
        self.write(assistant(999), {"type": "user", "pad": "x" * (warning._TAIL_BYTES + 10)})
        self.assertIsNone(warning.last_context_tokens(self.path))


class StageOf(unittest.TestCase):
    def test_stages(self):
        cases = [(120000, 0), (120001, 1), (170000, 1), (170001, 2), (220000, 2), (220001, 3), (520001, 9)]
        for tokens, stage in cases:
            self.assertEqual(warning.stage_of(tokens, 120000, 50000), stage, tokens)

    def test_no_step_warns_once(self):
        self.assertEqual(warning.stage_of(999999, 100, 0), 1)
        self.assertEqual(warning.stage_of(999999, 100, -5), 1)
        self.assertEqual(warning.stage_of(100, 100, 0), 0)


class Hook(TempDir):
    def run_hook(self, session="s1", threshold=None, payload=None, step=None):
        env = dict(os.environ, TEMP=self.dir, TMP=self.dir)
        env.pop("LOOPBGM_CONTEXT_WARN_TOKENS", None)
        env.pop("LOOPBGM_CONTEXT_WARN_STEP", None)
        if threshold is not None:
            env["LOOPBGM_CONTEXT_WARN_TOKENS"] = threshold
        if step is not None:
            env["LOOPBGM_CONTEXT_WARN_STEP"] = step
        data = payload if payload is not None else json.dumps({"transcript_path": self.path, "session_id": session}).encode()
        return subprocess.run([sys.executable, SCRIPT, "--hook"], input=data, capture_output=True, env=env, encoding=None)

    def test_warns_once_per_stage_over_the_default_threshold(self):
        self.write(assistant(1, 120000))
        first = self.run_hook()
        self.assertEqual(first.returncode, 0)
        context = json.loads(first.stdout.decode("utf-8"))["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "PostToolUse")
        self.assertIn("120,001", context["additionalContext"])
        self.assertIn("1 回目", context["additionalContext"])
        self.assertIn("新しい会話", context["additionalContext"])
        self.assertEqual(self.run_hook().stdout, b"", "same stage in the same session")
        self.assertNotEqual(self.run_hook(session="s2").stdout, b"", "another session")
        self.write(assistant(0, 170000))
        self.assertEqual(self.run_hook().stdout, b"", "still the first stage")
        self.write(assistant(0, 170001))
        second = self.run_hook()
        self.assertIn("2 回目", json.loads(second.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.run_hook().stdout, b"", "second stage already warned")
        self.write(assistant(0, 120001))
        self.assertEqual(self.run_hook().stdout, b"", "a smaller context after compaction does not warn again")

    def test_jumping_stages_warns_once(self):
        self.write(assistant(0, 400000))
        self.assertIn("6 回目".encode("utf-8"), self.run_hook().stdout)
        self.write(assistant(0, 410000))
        self.assertEqual(self.run_hook().stdout, b"")

    def test_step_zero_warns_only_once(self):
        self.write(assistant(0, 130000))
        self.assertNotEqual(self.run_hook(step="0").stdout, b"")
        self.write(assistant(0, 900000))
        self.assertEqual(self.run_hook(step="0").stdout, b"")

    def test_old_empty_mark_counts_as_the_first_stage(self):
        folder = os.path.join(self.dir, "loopbgm-context-warning")
        os.makedirs(folder)
        with open(os.path.join(folder, "s1"), "w", encoding="ascii"):
            pass  # #195 の印は空のファイル
        self.write(assistant(0, 130000))
        self.assertEqual(self.run_hook().stdout, b"")
        self.write(assistant(0, 180000))
        self.assertNotEqual(self.run_hook().stdout, b"")

    def test_existing_stage_mark_is_exclusive(self):
        # 並列の呼び出しが先に同じ段階の印を作っていたら、警告しない
        folder = os.path.join(self.dir, "loopbgm-context-warning")
        os.makedirs(folder)
        with open(os.path.join(folder, "s1-1"), "w", encoding="ascii"):
            pass
        self.write(assistant(0, 130000))
        self.assertEqual(self.run_hook().stdout, b"")
        self.write(assistant(0, 180000))
        self.assertNotEqual(self.run_hook().stdout, b"")
        self.assertTrue(os.path.exists(os.path.join(folder, "s1-2")))

    def test_silent_at_or_under_the_threshold(self):
        self.write(assistant(0, 120000))
        result = self.run_hook()
        self.assertEqual((result.returncode, result.stdout), (0, b""))

    def test_threshold_from_environment(self):
        self.write(assistant(0, 200))
        self.assertEqual(self.run_hook(threshold="1000").stdout, b"")
        self.assertNotEqual(self.run_hook(threshold="100").stdout, b"")
        self.assertEqual(self.run_hook(session="s3", threshold="0").stdout, b"", "0 disables")
        self.write(assistant(0, 200000))
        self.assertNotEqual(self.run_hook(session="s4", threshold="abc").stdout, b"", "invalid -> default")

    def test_unusual_session_id_cannot_escape_the_folder(self):
        self.write(assistant(0, 200000))
        name = "../" + uuid.uuid4().hex
        self.assertNotEqual(self.run_hook(session=name).stdout, b"")
        self.assertFalse(os.path.exists(os.path.join(self.dir, name.split("/")[1])))

    def test_no_warning_when_the_mark_cannot_be_created(self):
        self.write(assistant(0, 200000))
        with open(os.path.join(self.dir, "loopbgm-context-warning"), "w", encoding="utf-8"):
            pass  # フォルダの名前のファイルがあるので、印を作れない
        result = self.run_hook()
        self.assertEqual((result.returncode, result.stdout), (0, b""))

    def test_broken_input_never_blocks(self):
        for payload in [b"not json", b"[1]", b"{}"]:
            result = self.run_hook(payload=payload)
            self.assertEqual((result.returncode, result.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
