#!/usr/bin/env python3
# Name: audit_tags.py
# Description: Read-only audit of audio metadata tags and embedded cover
#              art across one or more music directories. Reports what is
#              missing or inconsistent. Modifies nothing.
# Usage: python3.11 audit_tags.py DIR [DIR ...]
# Inputs: directories of audio files (mp3, flac, m4a, ogg, wma)
# Outputs: a per-directory and overall summary printed to stdout
#
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11, ffprobe 7.x
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - ffprobe (from ffmpeg)
#
# Assumptions:
#   - Loose files follow the pattern "Artist - Album - NN - Title.ext"
# Failure Modes:
#   - Unreadable files are counted and listed, not fatal
# Notes:
#   - Strictly read-only. Never writes to the audited files.
#   - Exit codes: 0 always (this is a report, not a gate).

"""Read-only audit of audio tags and embedded cover art."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".wma"}
CORE_TAGS = ("title", "artist", "album", "track", "date", "genre")
SAMPLE_LIMIT = 25


def ffprobe(path):
    """Return parsed ffprobe JSON for a file, or None if it cannot be read."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None


def format_tags(data):
    """Return lower-cased, stripped format tags from ffprobe output."""
    raw = data.get("format", {}).get("tags") or {}
    return {k.lower(): (v or "").strip() for k, v in raw.items()}


def has_cover_art(data):
    """True if the file carries an attached picture (embedded cover art)."""
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            if (stream.get("disposition") or {}).get("attached_pic"):
                return True
    return False


def parse_filename(path):
    """Parse 'Artist - Album - NN - Title' from the stem, or None."""
    parts = path.stem.split(" - ")
    if len(parts) >= 4:
        return {
            "artist": parts[0].strip(),
            "album": parts[1].strip(),
            "track": parts[2].strip(),
            "title": " - ".join(parts[3:]).strip(),
        }
    return None


def norm(text):
    """Normalize a string for loose comparison."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def track_int(text):
    """Extract the leading integer of a track field (handles '4/12')."""
    match = re.match(r"\s*(\d+)", text or "")
    return int(match.group(1)) if match else None


def audit_dir(root):
    """Audit one directory tree. Returns (stats, missing_tag, albums, problems)."""
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    stats = Counter()
    missing_tag = Counter()
    albums = set()
    problems = []
    for path in files:
        stats["files"] += 1
        data = ffprobe(path)
        if data is None:
            stats["unreadable"] += 1
            problems.append(("unreadable", path))
            continue
        tags = format_tags(data)
        for tag in CORE_TAGS:
            if not tags.get(tag):
                missing_tag[tag] += 1
        if not has_cover_art(data):
            stats["no_art"] += 1
        if tags.get("album"):
            albums.add(norm(tags["album"]))
        named = parse_filename(path)
        if named is None:
            stats["no_filename_parse"] += 1
            continue
        mismatch = []
        for field in ("artist", "album", "title"):
            if tags.get(field) and norm(tags[field]) != norm(named[field]):
                mismatch.append(field)
        tag_tn = track_int(tags.get("track", ""))
        name_tn = track_int(named["track"])
        if tag_tn is not None and name_tn is not None and tag_tn != name_tn:
            mismatch.append("track")
        if mismatch:
            stats["tag_filename_mismatch"] += 1
            problems.append(("mismatch:" + ",".join(mismatch), path))
    return stats, missing_tag, albums, problems


def print_summary(label, stats, missing_tag, albums):
    total = stats["files"]
    print("\n== {0} ==".format(label))
    print("  files                 : {0}".format(total))
    print("  distinct albums (tag) : {0}".format(len(albums)))
    print("  missing embedded art  : {0}".format(stats["no_art"]))
    print("  unreadable            : {0}".format(stats["unreadable"]))
    print("  filename not parseable: {0}".format(stats["no_filename_parse"]))
    print("  tag/filename mismatch : {0}".format(stats["tag_filename_mismatch"]))
    missing_bits = ", ".join(
        "{0}={1}".format(t, missing_tag[t]) for t in CORE_TAGS if missing_tag[t]
    )
    print("  missing/blank tags    : {0}".format(missing_bits or "none"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only audit of audio tags and embedded cover art.")
    parser.add_argument("dirs", nargs="+", help="directories of audio files")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    overall = Counter()
    overall_missing = Counter()
    overall_albums = set()
    all_problems = []

    for raw in args.dirs:
        root = Path(raw).expanduser()
        if not root.is_dir():
            print("skip (not a directory): {0}".format(root), file=sys.stderr)
            continue
        stats, missing_tag, albums, problems = audit_dir(root)
        print_summary(root.name, stats, missing_tag, albums)
        overall.update(stats)
        overall_missing.update(missing_tag)
        overall_albums |= albums
        all_problems.extend(problems)

    print_summary("OVERALL", overall, overall_missing, overall_albums)

    if all_problems:
        print("\n== sample problem files (first {0}) ==".format(SAMPLE_LIMIT))
        for kind, path in all_problems[:SAMPLE_LIMIT]:
            print("  [{0}] {1}".format(kind, path))
        if len(all_problems) > SAMPLE_LIMIT:
            print("  ... and {0} more".format(len(all_problems) - SAMPLE_LIMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
