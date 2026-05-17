#!/usr/bin/env python3
# Name: make_dvd_iso.py
# Description: Build a DVD-Video ISO image from a single source video.
#              Transcodes to DVD-compliant MPEG-2, authors a menu-less
#              VIDEO_TS structure, and packs it into an ISO image.
# Usage: python3.11 make_dvd_iso.py INPUT [-o OUTPUT.iso] [options]
# Inputs: one source video file (any format ffmpeg can decode)
# Outputs: a .iso image containing a DVD-Video VIDEO_TS structure;
#          the ISO path is printed to stdout on success
#
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11, ffmpeg 7.x -- transcode stage only
#   Expected:
#     - Any Linux with Python 3.11+, ffmpeg, dvdauthor, xorriso
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - ffmpeg, ffprobe
#     - dvdauthor
#     - xorriso
#
# Assumptions:
#   - Single title, no menu: the disc auto-plays the one title
#   - The source has one video stream worth keeping
# Failure Modes:
#   - Missing external tool -> exit 2 with install hints
#   - Unreadable or non-video input -> exit 1
#   - A transcode / author / pack step exits non-zero -> exit 2
# Notes:
#   - The dvdauthor and xorriso stages are NOT yet verified end-to-end
#     on the test host; only the ffmpeg transcode stage is. Verify on
#     the first real run.
#   - Does not enforce the 4.7 GB single-layer limit. A long source at
#     the DVD bitrate (~6 Mbit/s) can overflow; trim it first.
#   - Exit codes: 0 ok, 1 bad input/usage, 2 tool missing or step failed.

"""Build a DVD-Video ISO image from a single source video file."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import discutil
from discutil import ToolSpec

TOOLS = [
    ToolSpec("ffmpeg", "ffmpeg", "FIELDKIT_FFMPEG",
             "install ffmpeg (e.g. dnf install ffmpeg, from RPM Fusion)"),
    ToolSpec("ffprobe", "ffprobe", "FIELDKIT_FFPROBE",
             "ships alongside ffmpeg"),
    ToolSpec("dvdauthor", "dvdauthor", "FIELDKIT_DVDAUTHOR",
             "install dvdauthor (e.g. dnf install dvdauthor, from RPM Fusion)"),
    ToolSpec("xorriso", "xorriso", "FIELDKIT_XORRISO",
             "install xorriso (e.g. dnf install xorriso)"),
]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Build a DVD-Video ISO from a single source video file.",
    )
    parser.add_argument("input", help="source video file")
    parser.add_argument("-o", "--output", metavar="ISO",
                        help="output .iso path (default: <input name>.iso)")
    parser.add_argument("--standard", choices=("auto", "ntsc", "pal"),
                        default="auto",
                        help="TV standard (default: auto-detect from frame rate)")
    parser.add_argument("--aspect", choices=("4:3", "16:9"),
                        help="display aspect ratio (default: .env or 16:9)")
    parser.add_argument("--volume-label", metavar="LABEL",
                        help="ISO volume label (default: derived from input name)")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep the intermediate work directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands without running them")
    return parser.parse_args(argv)


def resolve_standard(args, info, env):
    """Decide ntsc vs pal from the flag, then the frame rate, then .env."""
    if args.standard != "auto":
        standard = args.standard
    elif info.fps > 0:
        standard = discutil.pick_tv_standard(info.fps)
    else:
        standard = discutil.env_get(env, "FIELDKIT_DVD_STANDARD", "ntsc")
    standard = standard.lower()
    if standard not in ("ntsc", "pal"):
        raise discutil.InputError("invalid TV standard: {0}".format(standard))
    return standard


def resolve_output(args, src, env):
    """Decide where the finished .iso is written."""
    if args.output:
        return Path(args.output).expanduser().resolve()
    out_dir = discutil.env_get(env, "FIELDKIT_OUTPUT_DIR")
    base = Path(out_dir).expanduser() if out_dir else src.parent
    return (base / (src.stem + ".iso")).resolve()


def main(argv=None):
    discutil.require_python()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    dry_run = args.dry_run
    env = discutil.load_env()

    src = Path(args.input).expanduser()
    tools = discutil.require_tools(TOOLS, env, strict=not dry_run)
    info = discutil.probe(tools["ffprobe"], src, dry_run=dry_run)

    standard = resolve_standard(args, info, env)
    aspect = args.aspect or discutil.env_get(env, "FIELDKIT_DVD_ASPECT", "16:9")
    label = discutil.sanitize_volume_label(args.volume_label or src.stem)
    iso_path = resolve_output(args, src, env)

    work_base = discutil.env_get(env, "FIELDKIT_WORK_DIR")
    work = Path(tempfile.mkdtemp(prefix="fieldkit-dvd-", dir=work_base or None))
    mpg = work / "title.mpg"
    dvd_dir = work / "dvd"

    print(
        "DVD build: standard={0} aspect={1} label={2}\n"
        "  input : {3}\n"
        "  output: {4}".format(standard, aspect, label, src, iso_path),
        file=sys.stderr,
    )

    try:
        if not dry_run:
            iso_path.parent.mkdir(parents=True, exist_ok=True)

        discutil.run(
            [tools["ffmpeg"] or "ffmpeg", "-y", "-i", src,
             "-target", "{0}-dvd".format(standard), "-aspect", aspect, mpg],
            dry_run=dry_run, step="ffmpeg transcode",
        )

        # dvdauthor reads the target TV standard from the environment.
        author_env = {"VIDEO_FORMAT": standard.upper()}
        discutil.run(
            [tools["dvdauthor"] or "dvdauthor", "-o", dvd_dir, "-t", mpg],
            dry_run=dry_run, extra_env=author_env, step="dvdauthor (title)",
        )
        discutil.run(
            [tools["dvdauthor"] or "dvdauthor", "-o", dvd_dir, "-T"],
            dry_run=dry_run, extra_env=author_env, step="dvdauthor (toc)",
        )

        discutil.run(
            [tools["xorriso"] or "xorriso", "-as", "mkisofs",
             "-dvd-video", "-V", label, "-o", iso_path, dvd_dir],
            dry_run=dry_run, step="xorriso (iso)",
        )
    finally:
        if args.keep_temp:
            print("kept work directory: {0}".format(work), file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)

    if dry_run:
        print("dry run: no ISO written", file=sys.stderr)
    else:
        print(iso_path)
    return 0


def _entry():
    try:
        sys.exit(main())
    except discutil.InputError as exc:
        sys.exit("error: {0}".format(exc))
    except (discutil.ToolError, discutil.StepError) as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    _entry()
