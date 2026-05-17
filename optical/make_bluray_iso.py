#!/usr/bin/env python3
# Name: make_bluray_iso.py
# Description: Build a Blu-ray ISO image from a single source video.
#              Transcodes to Blu-ray-compliant H.264 + AC3, then has
#              tsMuxeR author the BDMV structure and write the ISO.
# Usage: python3.11 make_bluray_iso.py INPUT [-o OUTPUT.iso] [options]
# Inputs: one source video file (any format ffmpeg can decode)
# Outputs: a .iso image containing a Blu-ray BDMV structure; the ISO
#          path is printed to stdout on success
#
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11, ffmpeg 7.x -- transcode stage only
#   Expected:
#     - Any Linux with Python 3.11+, ffmpeg, and an ISO-capable tsMuxeR
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - ffmpeg, ffprobe (ffmpeg built with libx264)
#     - tsMuxeR -- a build that can write .iso output (the maintained
#       justdan96/tsMuxer fork does)
#
# Assumptions:
#   - Single playlist, no menu: the disc auto-plays the one title
#   - Source frame rate is snapped to the nearest legal Blu-ray rate
#   - Audio is re-encoded to AC3; sources beyond 5.1 are not supported
# Failure Modes:
#   - Missing external tool -> exit 2 with install hints
#   - Unreadable or non-video input -> exit 1
#   - A transcode / author step exits non-zero -> exit 2
# Notes:
#   - The tsMuxeR stage is NOT yet verified end-to-end on the test
#     host; only the ffmpeg transcode stage is. Verify on first run.
#   - tsMuxeR writes the ISO itself (correct UDF 2.50 for set-top
#     players). An older tsMuxeR without ISO output will fail here.
#   - Exit codes: 0 ok, 1 bad input/usage, 2 tool missing or step failed.

"""Build a Blu-ray ISO image from a single source video file."""

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
             "install ffmpeg built with libx264 (e.g. from RPM Fusion)"),
    ToolSpec("ffprobe", "ffprobe", "FIELDKIT_FFPROBE",
             "ships alongside ffmpeg"),
    ToolSpec("tsMuxeR", "tsMuxeR", "FIELDKIT_TSMUXER",
             "download a prebuilt tsMuxeR (justdan96/tsMuxer) and set "
             "FIELDKIT_TSMUXER to its path"),
]

# Source frame rates are snapped to a legal Blu-ray rate; these map
# that rate to the -r value ffmpeg wants and the fps label tsMuxeR
# wants. Keys are the floats returned by discutil.snap_bluray_fps().
FPS_FFMPEG = {
    23.976: "24000/1001", 24.0: "24", 25.0: "25",
    29.97: "30000/1001", 50.0: "50", 59.94: "60000/1001",
}
FPS_META = {
    23.976: "23.976", 24.0: "24", 25.0: "25",
    29.97: "29.97", 50.0: "50", 59.94: "59.94",
}

# Vertical resolution -> (width, height).
FRAME_SIZE = {"1080": (1920, 1080), "720": (1280, 720)}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Build a Blu-ray ISO from a single source video file.",
    )
    parser.add_argument("input", help="source video file")
    parser.add_argument("-o", "--output", metavar="ISO",
                        help="output .iso path (default: <input name>.iso)")
    parser.add_argument("--resolution", choices=("auto", "1080", "720"),
                        help="vertical resolution (default: auto from source)")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep the intermediate work directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands without running them")
    return parser.parse_args(argv)


def resolve_resolution(args, info, env):
    """Decide 1080 vs 720 from the flag, then .env, then the source."""
    choice = args.resolution or discutil.env_get(
        env, "FIELDKIT_BLURAY_RESOLUTION", "auto")
    if choice == "auto":
        choice = "1080" if info.height >= 1080 else "720"
    if choice not in FRAME_SIZE:
        raise discutil.InputError("invalid resolution: {0}".format(choice))
    return choice


def resolve_output(args, src, env):
    """Decide where the finished .iso is written."""
    if args.output:
        return Path(args.output).expanduser().resolve()
    out_dir = discutil.env_get(env, "FIELDKIT_OUTPUT_DIR")
    base = Path(out_dir).expanduser() if out_dir else src.parent
    return (base / (src.stem + ".iso")).resolve()


def build_meta(video_path, audio_path, fps_label):
    """Render the tsMuxeR meta file describing the Blu-ray streams."""
    lines = [
        "MUXOPT --blu-ray --vbr --auto-chapters=5",
        'V_MPEG4/ISO/AVC, "{0}", fps={1}, insertSEI, contSPS'.format(
            video_path, fps_label),
    ]
    if audio_path is not None:
        lines.append('A_AC3, "{0}"'.format(audio_path))
    return "\n".join(lines) + "\n"


def main(argv=None):
    discutil.require_python()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    dry_run = args.dry_run
    env = discutil.load_env()

    src = Path(args.input).expanduser()
    tools = discutil.require_tools(TOOLS, env, strict=not dry_run)
    info = discutil.probe(tools["ffprobe"], src, dry_run=dry_run)

    resolution = resolve_resolution(args, info, env)
    width, height = FRAME_SIZE[resolution]
    fps = discutil.snap_bluray_fps(info.fps)
    keyint = round(fps)
    iso_path = resolve_output(args, src, env)

    work_base = discutil.env_get(env, "FIELDKIT_WORK_DIR")
    work = Path(tempfile.mkdtemp(prefix="fieldkit-bd-", dir=work_base or None))
    video_es = work / "video.h264"
    audio_es = work / "audio.ac3"
    meta_path = work / "bluray.meta"

    print(
        "Blu-ray build: {0}p@{1}fps\n"
        "  input : {2}\n"
        "  output: {3}".format(resolution, FPS_META[fps], src, iso_path),
        file=sys.stderr,
    )

    scale = (
        "scale={w}:{h}:force_original_aspect_ratio=decrease,"
        "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    ).format(w=width, h=height)
    x264_params = (
        "bluray-compat=1:vbv-maxrate=40000:vbv-bufsize=30000:"
        "keyint={0}:colorprim=bt709:transfer=bt709:colormatrix=bt709"
    ).format(keyint)

    try:
        if not dry_run:
            iso_path.parent.mkdir(parents=True, exist_ok=True)

        discutil.run(
            [tools["ffmpeg"] or "ffmpeg", "-y", "-i", src, "-an",
             "-c:v", "libx264", "-preset", "medium",
             "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
             "-r", FPS_FFMPEG[fps], "-vf", scale, "-b:v", "20000k",
             "-x264-params", x264_params, video_es],
            dry_run=dry_run, step="ffmpeg video transcode",
        )

        audio_for_meta = None
        if info.has_audio:
            audio_for_meta = audio_es
            discutil.run(
                [tools["ffmpeg"] or "ffmpeg", "-y", "-i", src, "-vn",
                 "-c:a", "ac3", "-ar", "48000", "-b:a", "448k", audio_es],
                dry_run=dry_run, step="ffmpeg audio transcode",
            )
        else:
            discutil.warn("source has no audio stream; building a silent disc")

        meta_text = build_meta(video_es, audio_for_meta, FPS_META[fps])
        print("tsMuxeR meta file:\n" + meta_text, file=sys.stderr)
        if not dry_run:
            meta_path.write_text(meta_text, encoding="utf-8")

        discutil.run(
            [tools["tsMuxeR"] or "tsMuxeR", meta_path, iso_path],
            dry_run=dry_run, step="tsMuxeR (iso)",
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
