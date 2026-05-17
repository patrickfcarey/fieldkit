# Name: test_tag_music.py
# Description: Unit tests for the pure helper functions in tag_music.py.
# Usage: python3.11 -m unittest discover music/tests
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11
#   Dependencies:
#     - python >= 3.11 (standard library unittest only)
# Notes:
#   - Covers only functions with no network or external-tool dependency.

"""Unit tests for tag_music.py helper functions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tag_music.py lives in music/, one level above this tests/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tag_music  # noqa: E402


class LuceneEscapeTests(unittest.TestCase):
    def test_escapes_specials(self):
        self.assertEqual(tag_music.lucene_escape("Ahh!"), "Ahh\\!")
        self.assertEqual(tag_music.lucene_escape("Speak & Spell"),
                         "Speak \\& Spell")
        self.assertEqual(tag_music.lucene_escape("a:b"), "a\\:b")

    def test_leaves_plain_text(self):
        self.assertEqual(tag_music.lucene_escape("Rust in Peace"),
                         "Rust in Peace")


class CleanAlbumTests(unittest.TestCase):
    def test_strips_edition_suffix(self):
        self.assertEqual(
            tag_music.clean_album_for_lookup("Rust In Peace (Remastered)"),
            "Rust In Peace")
        self.assertEqual(
            tag_music.clean_album_for_lookup("Cryptic Writings [HDCD]"),
            "Cryptic Writings")

    def test_strips_disc_suffix(self):
        self.assertEqual(
            tag_music.clean_album_for_lookup(
                "Hardwired To Self-Destruct (Limited Edition) CD1"),
            "Hardwired To Self-Destruct")

    def test_leaves_plain_album(self):
        self.assertEqual(
            tag_music.clean_album_for_lookup("Master of Puppets"),
            "Master of Puppets")


class YearFromFolderTests(unittest.TestCase):
    def _year(self, folder):
        return tag_music.year_from_folder(Path("/x") / folder / "t.mp3")

    def test_bracketed_year_wins(self):
        self.assertEqual(
            self._year("1990 - Rust In Peace [2004 Remastered]"), "2004")

    def test_plain_year(self):
        self.assertEqual(self._year("1990 Rust In Peace @320"), "1990")

    def test_no_year(self):
        self.assertIsNone(self._year("Megadeth"))


class TrackFromFilenameTests(unittest.TestCase):
    def _track(self, stem):
        return tag_music.track_from_filename(Path("/x") / (stem + ".mp3"))

    def test_four_field_name(self):
        self.assertEqual(
            self._track("Megadeth - Rust In Peace - 03 - Take No Prisoners"),
            3)

    def test_leading_number(self):
        self.assertEqual(self._track("07 - Tornado Of Souls"), 7)
        self.assertEqual(self._track("07. Tornado Of Souls"), 7)

    def test_no_number(self):
        self.assertIsNone(self._track("Tornado Of Souls"))


class NormTests(unittest.TestCase):
    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(tag_music._norm("  Hello   World  "), "hello world")
        self.assertEqual(tag_music._norm(""), "")


class BuildFfmpegCmdTests(unittest.TestCase):
    def test_tag_only_mp3(self):
        cmd = tag_music.build_ffmpeg_cmd(
            Path("in.mp3"), Path("out.mp3"), None, {"genre": "Metal"})
        self.assertEqual(cmd[cmd.index("-map") + 1], "0")
        self.assertIn("-id3v2_version", cmd)
        self.assertIn("genre=Metal", cmd)

    def test_with_cover(self):
        cmd = tag_music.build_ffmpeg_cmd(
            Path("in.mp3"), Path("out.mp3"), Path("cover.jpg"), {})
        self.assertIn("0:a", cmd)
        self.assertIn("1:v", cmd)
        self.assertIn("attached_pic", cmd)


if __name__ == "__main__":
    unittest.main()
