# Name: discutil.py
# Description: Shared helpers for the optical disc-authoring tools
#              (make_dvd_iso.py, make_bluray_iso.py). Not executable.
# Usage: imported as a module -- `import discutil`
# Inputs: a repository .env file (optional); media files via ffprobe
# Outputs: none directly; provides functions to its importers
#
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11
#   Expected:
#     - Any Linux with Python 3.11+
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - ffprobe on PATH for probe(); other tools resolved by callers
#
# Assumptions:
#   - .env, when present, lives at the repository root (the first
#     ancestor directory containing .git or example.env)
# Failure Modes:
#   - Raises ToolError / InputError / StepError for expected problems;
#     callers map these to process exit codes
# Notes:
#   - Stdlib-only and kept parseable on Python 3.9 so require_python()
#     can fail with a clear message instead of a raw SyntaxError.

"""Shared helpers for the fieldkit optical disc-authoring tools."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MIN_PYTHON = (3, 11)

# Legal progressive Blu-ray frame rates. Source rates are snapped to
# the nearest of these by snap_bluray_fps().
BLURAY_FPS = (23.976, 24.0, 25.0, 29.97, 50.0, 59.94)


class FieldkitError(Exception):
    """Base class for expected, user-facing errors."""


class InputError(FieldkitError):
    """Bad arguments or a missing/unreadable input. Maps to exit code 1."""


class ToolError(FieldkitError):
    """A required external tool is missing. Maps to exit code 2."""


class StepError(FieldkitError):
    """An external command exited non-zero. Maps to exit code 2."""


def require_python(minimum=MIN_PYTHON):
    """Exit with a clear message if the interpreter is older than `minimum`."""
    if sys.version_info < minimum:
        want = ".".join(str(n) for n in minimum)
        have = ".".join(str(n) for n in sys.version_info[:3])
        sys.exit(
            "error: Python {0}+ is required, but this interpreter is {1}.\n"
            "       Re-run with a newer interpreter, e.g.: python{0} {2}".format(
                want, have, sys.argv[0]
            )
        )


def find_repo_root(start=None):
    """Walk upward from `start` to the repository root.

    The root is the first ancestor containing a .git entry or an
    example.env file. Returns a Path, or None if neither is found.
    """
    here = Path(start or __file__).resolve()
    for directory in [here] + list(here.parents):
        if (directory / ".git").exists() or (directory / "example.env").is_file():
            return directory
    return None


def load_env(repo_root=None):
    """Read the repository .env file into a dict.

    A missing .env is not an error: an empty dict is returned and
    callers fall back to their built-in defaults.
    """
    root = repo_root or find_repo_root()
    values: dict[str, str] = {}
    if root is None:
        return values
    env_path = Path(root) / ".env"
    if not env_path.is_file():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def env_get(env, key, default=""):
    """Return env[key] if it is set and non-empty, otherwise `default`."""
    val = env.get(key, "")
    return val if val else default


@dataclass
class ToolSpec:
    """Describes one external tool a script depends on."""

    logical: str       # name used in messages, e.g. "ffmpeg"
    exe: str           # binary searched for on PATH, e.g. "ffmpeg"
    env_key: str       # .env key that may hold an explicit path
    install_hint: str  # short instruction on how to install it


def resolve_tool(spec, env):
    """Return the path to a tool, or None if it cannot be located.

    An explicit, executable path given in .env wins; otherwise PATH is
    searched.
    """
    explicit = env_get(env, spec.env_key)
    if explicit:
        path = Path(explicit)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return None
    return shutil.which(spec.exe)


def require_tools(specs, env, *, strict=True):
    """Resolve every ToolSpec in `specs`.

    Returns {logical: path-or-None}. When a tool is missing: raise
    ToolError if `strict`, otherwise print a warning and continue (so
    --dry-run can still print the commands it would have run).
    """
    resolved = {}
    missing = []
    for spec in specs:
        path = resolve_tool(spec, env)
        resolved[spec.logical] = path
        if path is None:
            missing.append(spec)
    if missing:
        lines = ["the following required tools were not found:"]
        for spec in missing:
            lines.append("  - {0}: {1}".format(spec.logical, spec.install_hint))
        lines.append(
            "set an explicit path in .env ({0}) if a tool is installed "
            "elsewhere.".format(", ".join(s.env_key for s in missing))
        )
        message = "\n".join(lines)
        if strict:
            raise ToolError(message)
        warn(message)
    return resolved


def warn(message):
    """Print a warning to stderr."""
    print("warning: {0}".format(message), file=sys.stderr)


def run(cmd, *, dry_run=False, extra_env=None, step="command"):
    """Run an external command, echoing it first.

    The command is printed to stderr so stdout stays clean for
    scripting. In dry_run mode it is printed but not executed. A
    non-zero exit raises StepError tagged with `step`.
    """
    cmd = [str(c) for c in cmd]
    print("$ " + shlex.join(cmd), file=sys.stderr)
    if dry_run:
        return
    proc_env = None
    if extra_env:
        proc_env = dict(os.environ)
        proc_env.update(extra_env)
    result = subprocess.run(cmd, env=proc_env)
    if result.returncode != 0:
        raise StepError("{0} failed (exit {1})".format(step, result.returncode))


@dataclass
class MediaInfo:
    """The subset of source-media properties the disc tools care about."""

    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def _parse_rate(text):
    """Parse an ffprobe rate string such as '30000/1001' into a float."""
    text = (text or "").strip()
    if not text or text == "0/0":
        return 0.0
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            denominator = float(den)
            return float(num) / denominator if denominator else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe(ffprobe, path, *, dry_run=False):
    """Inspect a media file with ffprobe and return a MediaInfo.

    If ffprobe is unavailable during a dry run, a placeholder is
    returned so callers can still build and print their commands.
    """
    src = Path(path)
    if not src.is_file():
        raise InputError("input file not found: {0}".format(src))
    if ffprobe is None:
        if dry_run:
            warn("ffprobe unavailable; using placeholder media info for dry run")
            return MediaInfo(1920, 1080, 24.0, 0.0, True)
        raise ToolError("ffprobe is required to inspect the input")
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(src)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise InputError(
            "ffprobe could not read {0}: {1}".format(src, result.stderr.strip())
        )
    data = json.loads(result.stdout or "{}")
    video = None
    has_audio = False
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            video = stream
        elif kind == "audio":
            has_audio = True
    if video is None:
        raise InputError("no video stream found in {0}".format(src))
    fps = _parse_rate(video.get("r_frame_rate")) or _parse_rate(
        video.get("avg_frame_rate")
    )
    duration = 0.0
    for candidate in (video.get("duration"),
                      data.get("format", {}).get("duration")):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue
    return MediaInfo(
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        duration=duration,
        has_audio=has_audio,
    )


def pick_tv_standard(fps):
    """Return 'pal' (25/50 fps) or 'ntsc' (everything else) for `fps`."""
    return "pal" if round(fps) in (25, 50) else "ntsc"


def snap_bluray_fps(fps):
    """Snap an arbitrary frame rate to the nearest legal Blu-ray rate."""
    if fps <= 0:
        return 24.0
    return min(BLURAY_FPS, key=lambda legal: abs(legal - fps))


def sanitize_volume_label(name, *, limit=32):
    """Build a disc volume label from `name`.

    Keeps uppercase A-Z, 0-9 and underscore (the ISO9660-safe set);
    any other character becomes an underscore. The result is trimmed
    to `limit` characters and falls back to 'DISC' if empty.
    """
    chars = []
    for ch in str(name).upper():
        if ch.isascii() and (ch.isalnum() or ch == "_"):
            chars.append(ch)
        else:
            chars.append("_")
    label = "".join(chars).strip("_")[:limit]
    return label or "DISC"
