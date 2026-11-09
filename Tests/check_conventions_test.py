# Tests/check_conventions.py の回帰テスト。
#
#   python Tests/check_conventions_test.py
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_conventions as cc  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_conventions.py")
TODAY = datetime.date(2026, 11, 9)


class CheckConventions(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="loopbgm_conv_test_", dir=cc.ROOT)
        self.rel = os.path.relpath(self.dir, cc.ROOT).replace("\\", "/")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, data: bytes):
        with open(os.path.join(self.dir, name), "wb") as file:
            file.write(data)
        return f"{self.rel}/{name}"

    def rules(self, rel):
        errors, warnings = cc.check_file(rel, today=TODAY)
        return [e[2] for e in errors], [w[2] for w in warnings]

    def test_ps1_needs_bom_and_others_must_not_have_it(self):
        self.assertEqual(self.rules(self.write("a.ps1", b"Write-Host 1\n"))[0], ["bom"])
        self.assertEqual(self.rules(self.write("b.ps1", cc.BOM + b"Write-Host 1\n"))[0], [])
        self.assertEqual(self.rules(self.write("c.py", cc.BOM + b"x = 1\n"))[0], ["bom"])

    def test_fix_adds_and_removes_bom(self):
        ps1 = self.write("a.ps1", b"Write-Host 1\n")
        py = self.write("c.py", cc.BOM + b"x = 1\n")
        cc.fix_file(ps1)
        cc.fix_file(py)
        self.assertEqual(self.rules(ps1)[0], [])
        self.assertEqual(self.rules(py)[0], [])

    def test_markdown_review_marker(self):
        ok = "# T\n\n<!-- last-reviewed: 2026-11-01 -->\n".encode()
        self.assertEqual(self.rules(self.write("ok.md", ok)), ([], []))
        self.assertEqual(self.rules(self.write("none.md", b"# T\n"))[0], ["review"])
        two = "# T\n<!-- last-reviewed: 2026-11-01 -->\n<!-- last-reviewed: 2026-11-02 -->\n".encode()
        self.assertEqual(self.rules(self.write("two.md", two))[0], ["review"])
        future = "# T\n<!-- last-reviewed: 2027-01-01 -->\n".encode()
        self.assertEqual(self.rules(self.write("future.md", future))[0], ["review"])
        stale = "# T\n<!-- last-reviewed: 2026-01-01 -->\n".encode()
        self.assertEqual(self.rules(self.write("stale.md", stale)), ([], ["review"]))
        inline = "# T\n<!-- last-reviewed: 2026-11-01 -->\nQuote it inline: `<!-- last-reviewed: YYYY-MM-DD -->`.\n".encode()
        self.assertEqual(self.rules(self.write("inline.md", inline)), ([], []))

    def test_audio_is_rejected(self):
        self.assertEqual(self.rules(self.write("x.wav", b"RIFF"))[0], ["audio"])
        self.assertEqual(self.rules(self.write("x.OGG", b"OggS"))[0], ["audio"])

    def test_hook_reports_with_exit_code_2(self):
        path = os.path.join(self.dir, "a.ps1")
        with open(path, "wb") as file:
            file.write(b"Write-Host 1\n")
        payload = json.dumps({"tool_input": {"file_path": path}}).encode()
        r = subprocess.run([sys.executable, SCRIPT, "--hook"], input=payload, capture_output=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("[bom]", r.stderr.decode("utf-8"))
        outside = json.dumps({"tool_input": {"file_path": os.path.join(tempfile.gettempdir(), "x.ps1")}}).encode()
        self.assertEqual(subprocess.run([sys.executable, SCRIPT, "--hook"], input=outside).returncode, 0)


if __name__ == "__main__":
    unittest.main()
