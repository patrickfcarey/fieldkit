#!/usr/bin/env python3
# Name: gen_playlists.py
# Description: Generate an extended M3U playlist for every album folder in a
#              music library. One .m3u per folder, named after the folder,
#              tracks sorted by track tag then filename.
# Usage: python3.11 gen_playlists.py DIR [DIR ...] [--dry-run]
# Inputs: directories of audio files (mp3, flac, m4a)
# Outputs: one .m3u file written into each album folder

"""Generate extended M3U playlists for every album folder in a music library."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
AUDIO_EXTS = {".mp3", ".flac", ".m4a"}


def require_python(minimum=MIN_PYTHON):
    if sys.version_info < minimum:
        want = ".".join(str(n) for n in minimum)
        have = ".".join(str(n) for n in sys.version_info[:3])
        sys.exit("error: Python {0}+ required, this is {1}".format(want, have))


def ffprobe_tags(path):
    """Return (duration_seconds, artist, title) from ffprobe, or (None, '', '')."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None, "", ""
    if result.returncode != 0:
        return None, "", ""
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, "", ""
    tags = {k.lower(): v for k, v in
            (data.get("format", {}).get("tags") or {}).items()}
    duration = data.get("format", {}).get("duration")
    duration = int(float(duration)) if duration else None
    return duration, tags.get("artist", ""), tags.get("title", path.stem)


def track_sort_key(path):
    """Sort key: numeric track prefix from filename, then full name."""
    stem = path.stem
    # four-field format: artist - album - NN - title
    parts = stem.split(" - ")
    if len(parts) >= 4 and re.fullmatch(r"\d{1,3}", parts[2].strip()):
        return (int(parts[2].strip()), stem)
    match = re.match(r"\s*(\d{1,3})[ .\-_]", stem)
    if match:
        return (int(match.group(1)), stem)
    return (9999, stem)


def write_m3u(folder, tracks, dry_run):
    """Write an extended M3U into `folder` for the given track paths."""
    name = folder.name
    m3u_path = folder / (name + ".m3u")
    lines = ["#EXTM3U", ""]
    for track in tracks:
        duration, artist, title = ffprobe_tags(track)
        dur_str = str(duration) if duration is not None else "-1"
        label = "{0} - {1}".format(artist, title) if artist else title
        lines.append("#EXTINF:{0},{1}".format(dur_str, label))
        lines.append(track.name)
        lines.append("")
    content = "\n".join(lines)
    if dry_run:
        print("  would write: {0}".format(m3u_path))
    else:
        m3u_path.write_text(content, encoding="utf-8")
        print("  wrote: {0}".format(m3u_path))
    return m3u_path


def collect_folders(roots):
    """Return a dict of folder -> sorted list of audio files."""
    folders: dict[Path, list[Path]] = {}
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            print("skip (not a directory): {0}".format(root), file=sys.stderr)
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in AUDIO_EXTS:
                folders.setdefault(path.parent, []).append(path)
    for folder in folders:
        folders[folder].sort(key=track_sort_key)
    return folders


def main():
    require_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dirs", nargs="+", help="directories of audio files")
    parser.add_argument("--dry-run", action="store_true",
                        help="report without writing")
    args = parser.parse_args()

    folders = collect_folders(args.dirs)
    print("{0}: {1} album folder(s)\n".format(
        "DRY RUN" if args.dry_run else "GENERATING",
        len(folders)))

    written = skipped = 0
    for folder in sorted(folders):
        tracks = folders[folder]
        m3u_path = folder / (folder.name + ".m3u")
        if m3u_path.exists() and not args.dry_run:
            # overwrite — tags may have changed after tagging run
            pass
        print("FOLDER {0} ({1} tracks)".format(folder.name, len(tracks)))
        write_m3u(folder, tracks, args.dry_run)
        written += 1

    print("\n== totals ==")
    print("  {0}: {1}".format(
        "would write" if args.dry_run else "written", written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
