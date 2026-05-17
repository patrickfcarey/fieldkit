# Name: test_discutil.py
# Description: Unit tests for the pure helper functions in discutil.py.
# Usage: python3.11 -m unittest discover optical/tests
#        (or: python3.11 optical/tests/test_discutil.py)
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11
#   Dependencies:
#     - python >= 3.11 (standard library unittest only)
# Notes:
#   - Covers only functions with no external-tool dependency. The
#     ffmpeg/ffprobe-backed paths are exercised by real builds.

"""Unit tests for discutil.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# discutil.py lives in optical/, one level above this tests/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discutil  # noqa: E402


class ParseRateTests(unittest.TestCase):
    def test_fraction(self):
        self.assertAlmostEqual(discutil._parse_rate("30000/1001"), 29.97, places=2)
        self.assertAlmostEqual(discutil._parse_rate("24000/1001"), 23.976, places=3)

    def test_integer(self):
        self.assertEqual(discutil._parse_rate("25"), 25.0)

    def test_degenerate(self):
        self.assertEqual(discutil._parse_rate(""), 0.0)
        self.assertEqual(discutil._parse_rate("0/0"), 0.0)
        self.assertEqual(discutil._parse_rate("garbage"), 0.0)
        self.assertEqual(discutil._parse_rate("5/0"), 0.0)


class TvStandardTests(unittest.TestCase):
    def test_pal_rates(self):
        self.assertEqual(discutil.pick_tv_standard(25.0), "pal")
        self.assertEqual(discutil.pick_tv_standard(50.0), "pal")

    def test_ntsc_rates(self):
        for fps in (23.976, 24.0, 29.97, 30.0, 59.94):
            self.assertEqual(discutil.pick_tv_standard(fps), "ntsc")


class SnapBlurayFpsTests(unittest.TestCase):
    def test_snaps_to_nearest_legal_rate(self):
        self.assertEqual(discutil.snap_bluray_fps(30.0), 29.97)
        self.assertEqual(discutil.snap_bluray_fps(23.98), 23.976)
        self.assertEqual(discutil.snap_bluray_fps(60.0), 59.94)
        self.assertEqual(discutil.snap_bluray_fps(48.0), 50.0)

    def test_exact_rate_is_preserved(self):
        self.assertEqual(discutil.snap_bluray_fps(25.0), 25.0)

    def test_nonpositive_defaults_to_24(self):
        self.assertEqual(discutil.snap_bluray_fps(0.0), 24.0)
        self.assertEqual(discutil.snap_bluray_fps(-5.0), 24.0)


class VolumeLabelTests(unittest.TestCase):
    def test_keeps_safe_characters(self):
        self.assertEqual(discutil.sanitize_volume_label("MyMovie01"), "MYMOVIE01")

    def test_replaces_unsafe_characters(self):
        self.assertEqual(discutil.sanitize_volume_label("My Movie!"), "MY_MOVIE")
        self.assertEqual(discutil.sanitize_volume_label("a-b.c"), "A_B_C")

    def test_non_ascii_dropped(self):
        self.assertEqual(discutil.sanitize_volume_label("café"), "CAF")

    def test_empty_falls_back(self):
        self.assertEqual(discutil.sanitize_volume_label(""), "DISC")
        self.assertEqual(discutil.sanitize_volume_label("___"), "DISC")

    def test_length_is_capped(self):
        self.assertEqual(len(discutil.sanitize_volume_label("X" * 100)), 32)


class EnvTests(unittest.TestCase):
    def test_env_get(self):
        env = {"A": "value", "B": ""}
        self.assertEqual(discutil.env_get(env, "A"), "value")
        self.assertEqual(discutil.env_get(env, "B", "fallback"), "fallback")
        self.assertEqual(discutil.env_get(env, "MISSING", "fallback"), "fallback")

    def test_load_env_parses_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text(
                "# a comment\n"
                "\n"
                "FIELDKIT_DVD_STANDARD=pal\n"
                'FIELDKIT_OUTPUT_DIR="/srv/iso"\n'
                "FIELDKIT_WORK_DIR='/tmp/work'\n"
                "  FIELDKIT_DVD_ASPECT = 4:3  \n",
                encoding="utf-8",
            )
            env = discutil.load_env(repo_root=tmp)
        self.assertEqual(env["FIELDKIT_DVD_STANDARD"], "pal")
        self.assertEqual(env["FIELDKIT_OUTPUT_DIR"], "/srv/iso")
        self.assertEqual(env["FIELDKIT_WORK_DIR"], "/tmp/work")
        self.assertEqual(env["FIELDKIT_DVD_ASPECT"], "4:3")

    def test_load_env_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discutil.load_env(repo_root=tmp), {})


if __name__ == "__main__":
    unittest.main()
