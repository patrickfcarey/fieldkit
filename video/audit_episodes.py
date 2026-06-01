# Name: audit_episodes.py
# Description: Read-only structural audit of a TV/anime library. Reports, per show and
#              overall, how episodes are organized (season subfolders vs flat), how many
#              video files exist, and which episode-naming scheme each show uses
#              (SxxExx, NxNN, "Season N", absolute number, fansub [group] prefix).
#              Makes NO changes.
# Usage: python3.11 audit_episodes.py DIR [DIR ...]
# Inputs: One or more directories whose immediate children are show folders (or loose files)
# Outputs: A human-readable report to stdout (pattern tallies + per-show lines)
#
# Environment:
#   Tested:
#     - Oracle Linux 9.7 (UEK kernel)
#     - Python 3.11
#   Expected:
#     - Oracle Linux 9.x / RHEL 9 compatible systems
#   Dependencies:
#     - python >= 3.11 (standard library only)
#
# Assumptions:
#   - Immediate children of each DIR are individual shows (folders) or stray episode files.
#   - UTF-8 filenames.
# Failure Modes:
#   - DIR does not exist (reported, skipped).
# Notes:
#   - Pattern is sampled from the first video file found per show, so the tally is a guide,
#     not a guarantee that every episode in a show matches. Read-only by design.

import os
import re
import sys

VIDEO_EXTS = {
    ".avi", ".mp4", ".mkv", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg",
    ".flv", ".ts", ".webm", ".ogm", ".rm", ".rmvb",
}

# Episode-naming schemes, checked in priority order against a sampled filename.
PATTERNS = [
    ("SxxExx",    re.compile(r"[sS]\d{1,2}[\s._-]?[eE]\d{1,3}")),
    ("NxNN",      re.compile(r"\b\d{1,2}x\d{1,3}\b")),
    ("Season N",  re.compile(r"season[\s._-]?\d", re.I)),
    ("EpNN",      re.compile(r"\b[eE]p?\s?\d{1,3}\b")),
    ("fansub[]",  re.compile(r"^\[[^\]]+\]")),
    ("absNum",    re.compile(r"\b\d{1,3}\b")),
]
SEASON_DIR = re.compile(r"season[\s._-]?\d", re.I)
BARE_NUM_DIR = re.compile(r"^\d{1,2}$")


def is_video(name):
    return os.path.splitext(name)[1].lower() in VIDEO_EXTS


def count_videos(path):
    total = 0
    for _, _, files in os.walk(path):
        for f in files:
            if not f.endswith("Zone.Identifier") and is_video(f):
                total += 1
    return total


def first_video(path):
    for _, _, files in os.walk(path):
        for f in sorted(files):
            if not f.endswith("Zone.Identifier") and is_video(f):
                return f
    return ""


def classify(sample):
    for label, rx in PATTERNS:
        if sample and rx.search(sample):
            return label
    return "none"


def audit(root):
    if not os.path.isdir(root):
        print(f"!! not a directory: {root}\n")
        return
    entries = sorted(
        (e for e in os.listdir(root)
         if not e.endswith("Zone.Identifier") and not e.startswith(".")),
        key=str.lower,
    )
    folders = [e for e in entries if os.path.isdir(os.path.join(root, e))]
    loose = [e for e in entries if e not in folders and is_video(e)]

    tally = {}
    with_seasons = 0
    flat_shows = 0
    lines = []
    for e in folders:
        full = os.path.join(root, e)
        subdirs = [d for d in os.listdir(full)
                   if os.path.isdir(os.path.join(full, d)) and not d.startswith(".")]
        has_seasons = any(SEASON_DIR.search(d) or BARE_NUM_DIR.match(d) for d in subdirs)
        vids = count_videos(full)
        sample = first_video(full)
        scheme = classify(sample)
        tally[scheme] = tally.get(scheme, 0) + 1
        if has_seasons:
            with_seasons += 1
            shape = "season-subfolders"
        elif vids > 1:
            flat_shows += 1
            shape = "FLAT (no season folders)"
        else:
            shape = "single-file/other"
        lines.append(f"  [{vids:4d} vid] [{scheme:9}] {e}/   <{shape}>")
        if sample:
            lines.append(f"             e.g. {sample}")

    print(f"=== {root}")
    print(f"top-level: {len(entries)} entries  ({len(folders)} show folders, {len(loose)} loose video files)")
    print(f"shows with season subfolders: {with_seasons}/{len(folders)}   |   flat shows: {flat_shows}")
    if loose:
        print(f"loose top-level video files: {len(loose)} (e.g. {loose[0]})")
    print("episode-naming schemes (sampled, one per show):")
    for label, _ in PATTERNS:
        if label in tally:
            print(f"  {label:9} {tally[label]}")
    if tally.get("none"):
        print(f"  {'none':9} {tally['none']}")
    print("\nper-show:")
    print("\n".join(lines))
    print()


def main(argv):
    if len(argv) < 2:
        print("usage: python3.11 audit_episodes.py DIR [DIR ...]", file=sys.stderr)
        return 2
    for root in argv[1:]:
        audit(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
