# Name: test_fix_tables.py
# Description: Tests for markdown/fix_tables.py: the built-in worked examples, plus the
#              command line (--check, --in-place, CRLF files, a missing file).
# Usage: python3 -m unittest discover -s markdown/tests
# Environment:
#   Tested:
#     - Oracle Linux Server 9.7 (WSL2), Python 3.9.25
#   Dependencies:
#     - python >= 3.9 (standard library only)

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "fix_tables.py")
sys.path.insert(0, os.path.join(HERE, ".."))

import fix_tables  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, SCRIPT] + list(args),
                          capture_output=True, text=True)


class FixTablesTest(unittest.TestCase):

    def test_built_in_examples_pass(self):
        self.assertEqual(fix_tables.run_self_test(), 0)

    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                             encoding="utf-8", newline="")
        handle.write(text)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def read(self, path):
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()

    def test_check_reports_a_messy_file_and_changes_nothing(self):
        path = self.write("| a | bb |\n|-|-|\n| ccc | d |\n")
        result = run("--check", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("would change", result.stdout)
        self.assertEqual(self.read(path), "| a | bb |\n|-|-|\n| ccc | d |\n")

    def test_check_passes_a_tidy_file(self):
        path = self.write("| a   | b   |\n| --- | --- |\n| 1   | 2   |\n")
        self.assertEqual(run("--check", path).returncode, 0)

    def test_in_place_rewrites_and_keeps_crlf(self):
        path = self.write("| a | b |\r\n|-|-|\r\n| 1 | 2 |\r\n")
        self.assertEqual(run("--in-place", path).returncode, 0)
        self.assertEqual(self.read(path), "| a   | b   |\r\n| --- | --- |\r\n| 1   | 2   |\r\n")

    def test_missing_file_is_exit_2(self):
        result = run(os.path.join(HERE, "no-such-file.md"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no-such-file.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
