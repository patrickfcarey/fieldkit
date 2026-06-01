# Name: map_absolute_episodes.py
# Description: Resolve an absolute-numbered show folder (common for anime fansub rips) into a
#              Plex layout by looking the series up on TheTVDB. It reads each file's absolute
#              episode number, fetches the series' aired-order episode list from TheTVDB
#              (which carries seasonNumber + number + absoluteNumber + name), maps each absolute
#              number to its season/episode, and plans renames to:
#                  Show (Year)/Season NN/Show - sNNeNN - Title.ext
#              PREVIEW by default; --apply renames with a log and a reversible undo script.
#              --offline shows only the absolute numbers parsed from filenames (no network),
#              so you can sanity-check parsing before spending an API call.
# Usage: python3.11 map_absolute_episodes.py SHOW_DIR [--name NAME] [--tvdb-id ID]
#                                             [--order default|official|dvd|absolute]
#                                             [--offline] [--apply] [--log-dir DIR]
# Inputs: One show directory whose episodes use absolute numbering. FIELDKIT_TVDB_API_KEY in .env
#         (and FIELDKIT_TVDB_PIN if your key is user-supported). Key: https://thetvdb.com/dashboard.
# Outputs: A plan to stdout; on --apply also <log-dir>/map-absolute-<show>-<date>.log and
#          <log-dir>/undo-map-absolute-<show>-<date>.sh
#
# Environment:
#   Tested:
#     - Oracle Linux 9.7 (UEK kernel)
#     - Python 3.11
#     - Offline filename parsing validated; TheTVDB v4 calls require a user-supplied API key.
#   Expected:
#     - Oracle Linux 9.x / RHEL 9 compatible systems with outbound HTTPS
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - A TheTVDB v4 API key (FIELDKIT_TVDB_API_KEY)
#
# Assumptions:
#   - SHOW_DIR holds one show's episodes (flat or in subfolders), absolute-numbered.
#   - Same-filesystem moves. UTF-8 filenames.
# Failure Modes:
#   - Missing/invalid FIELDKIT_TVDB_API_KEY (clear message, exit 4).
#   - No series match / ambiguous parse (reported; use --tvdb-id or --name; nothing applied).
# Notes:
#   - Filename absolute-number parsing is heuristic; always read the preview before --apply.
#   - Episode titles come from TheTVDB, so output names are authoritative, not scraped from the rip.

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VIDEO_EXTS = {
    ".avi", ".mp4", ".mkv", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg",
    ".flv", ".ts", ".webm", ".ogm", ".rm", ".rmvb",
}
API = "https://api4.thetvdb.com/v4"
USER_AGENT = "fieldkit/video (https://github.com/patrickfcarey/fieldkit)"

# absolute-number extraction patterns, tried in order against a cleaned filename
EP_WORD = re.compile(r"\b(?:ep|episode|session|e)[ ._-]*(\d{1,3})\b", re.I)
DASH_MID = re.compile(r"[-–][ _]*(\d{1,3})[ _]*[-–]")
DASH_END = re.compile(r"[-–][ _]*(\d{1,3})\s*$")
YEAR = re.compile(r"\((?:19|20)\d{2}\)")
JUNK_WORD = re.compile(
    r"\b(480p|720p|1080p|2160p|x264|x265|hevc|10bit|8bit|bd|bdrip|bluray|web[ ._-]?dl|"
    r"webrip|aac|flac|ac3|dual audio|dvdrip)\b",
    re.I,
)


def _require_py311():
    if sys.version_info < (3, 11):
        have = ".".join(str(n) for n in sys.version_info[:3])
        sys.exit(f"error: Python 3.11+ required, this is {have}")


def _repo_root():
    here = Path(__file__).resolve()
    for directory in [here] + list(here.parents):
        if (directory / ".git").exists() or (directory / "example.env").is_file():
            return directory
    return None


def _dotenv_value(key):
    root = _repo_root()
    if root is None:
        return ""
    env_path = root / ".env"
    if not env_path.is_file():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        if name.strip() == key:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            return val
    return ""


def _cfg(key):
    return os.environ.get(key, "").strip() or _dotenv_value(key).strip()


def http_json(url, token=None, payload=None):
    """GET (or POST when payload is given) returning parsed JSON, or raising on failure."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    time.sleep(0.25)  # be polite to the API
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tvdb_login(api_key, pin):
    body = {"apikey": api_key}
    if pin:
        body["pin"] = pin
    data = http_json(f"{API}/login", payload=body)
    token = (data.get("data") or {}).get("token")
    if not token:
        raise RuntimeError("login succeeded but no token returned")
    return token


def tvdb_search(token, query):
    url = f"{API}/search?" + urllib.parse.urlencode({"query": query, "type": "series"})
    return (http_json(url, token=token).get("data") or [])


def tvdb_episode_map(token, series_id, order):
    """Return {absoluteNumber: (season, episode, name)} for a series, across all pages."""
    mapping = {}
    page = 0
    while True:
        url = f"{API}/series/{series_id}/episodes/{order}?page={page}"
        data = http_json(url, token=token).get("data") or {}
        for ep in data.get("episodes", []):
            absn = ep.get("absoluteNumber")
            if absn is None:
                continue
            mapping[int(absn)] = (
                int(ep.get("seasonNumber") or 0),
                int(ep.get("number") or 0),
                (ep.get("name") or "").strip(),
            )
        nxt = (data.get("links") or {}).get("next")
        if not nxt:
            break
        page += 1
        if page > 50:  # safety stop for very long-running series
            break
    return mapping


def is_video(name):
    return os.path.splitext(name)[1].lower() in VIDEO_EXTS


def extract_absolute(fname):
    """Best-effort absolute episode number from a filename, or None if unclear."""
    s = os.path.splitext(fname)[0]
    s = re.sub(r"\[[^\]]*\]", " ", s)          # drop [group]/[hash]/[720p]
    s = YEAR.sub(" ", s)
    s = JUNK_WORD.sub(" ", s)
    for rx in (EP_WORD, DASH_MID, DASH_END):
        m = rx.search(s)
        if m:
            return int(m.group(1))
    nums = re.findall(r"(?<!\d)(\d{1,3})(?!\d)", s)
    return int(nums[0]) if len(nums) == 1 else None   # only if unambiguous


def clean_name(folder):
    """Return (search_query, year_or_None) from a messy folder name."""
    s = re.sub(r"^\[[^\]]*\]\s*", "", folder)            # drop leading [group]
    ym = YEAR.search(s)
    year = ym.group(0)[1:-1] if ym else None
    s = YEAR.sub(" ", s)                                 # remove (YYYY) from the query
    s = re.split(r"\b(complete|s\d{1,2}\b|season|480p|720p|1080p|2160p|bdrip|bluray|"
                 r"dual audio|x264|x265)\b", s, flags=re.I)[0]
    s = re.sub(r"[ _-]+\d{1,3}\s*-\s*\d{1,3}\s*$", "", s)  # trailing "1-26" (dash form)
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+\d{1,3}\s+\d{1,3}\s*$", "", s)         # trailing "1 26" (spaced form)
    return re.sub(r"\s{2,}", " ", s).strip(" -._"), year


def collect(show_dir):
    """Yield (rel_path, abs_number_or_None, ext) for each video file under show_dir."""
    for dirpath, _, files in os.walk(show_dir):
        for f in sorted(files):
            if f.endswith("Zone.Identifier") or not is_video(f):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), show_dir)
            yield rel, extract_absolute(f), os.path.splitext(f)[1].lower()


def sanitize(text):
    """Make an episode title safe for a filename."""
    return re.sub(r'[\\/:*?"<>|]', "", text).strip()


def plan_renames(show_dir, label, year, ep_map):
    """Return (moves, unparsed, unmapped). moves = list of (rel_src, rel_dst)."""
    moves, unparsed, unmapped = [], [], []
    folder = f"{label} ({year})" if year else label
    for rel, absn, ext in collect(show_dir):
        if absn is None:
            unparsed.append(rel)
            continue
        if absn not in ep_map:
            unmapped.append((rel, absn))
            continue
        season, ep, title = ep_map[absn]
        name = f"{label} - s{season:02d}e{ep:02d}"
        if title:
            name += f" - {sanitize(title)}"
        moves.append((rel, f"{folder}/Season {season:02d}/{name}{ext}"))
    return moves, unparsed, unmapped


def do_apply(show_dir, moves, log_dir, date):
    """Apply moves within the show's parent; reversible (undo rewritten after each move)."""
    parent = os.path.dirname(show_dir)
    rel = lambda p: os.path.relpath(p, parent)
    os.makedirs(log_dir, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(show_dir.rstrip("/"))) or "show"
    undo_path = os.path.join(log_dir, f"undo-map-absolute-{tag}-{date}.sh")
    log_path = os.path.join(log_dir, f"map-absolute-{tag}-{date}.log")
    undo, loglines = [], []

    def flush():
        with open(undo_path, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\n# Reverse map_absolute_episodes.py --apply (best-effort).\n")
            fh.write(f'cd "{parent}"\n')
            fh.write("\n".join(reversed(undo)) + "\n")
        os.chmod(undo_path, 0o755)

    flush()
    moved = 0
    for rel_src, rel_dst in moves:
        src = os.path.join(show_dir, rel_src)
        dst = os.path.join(parent, rel_dst)
        if os.path.abspath(src) == os.path.abspath(dst) or not os.path.exists(src):
            continue
        if os.path.exists(dst):
            loglines.append(f"SKIP collision: {rel_dst}")
            continue
        season_dir = os.path.dirname(dst)
        if not os.path.isdir(season_dir):
            os.makedirs(season_dir)
            undo.append(f'rmdir -- "{rel(season_dir)}" 2>/dev/null || true')
            flush()
        os.rename(src, dst)
        undo.append(f'mv -n -- "{rel(dst)}" "{rel(src)}"')
        flush()
        loglines.append(f"{rel_src}  ->  {rel_dst}")
        moved += 1
    # prune emptied subfolders of the (old) show dir
    for dirpath, _, _ in os.walk(show_dir, topdown=False):
        try:
            if os.path.isdir(dirpath) and not os.listdir(dirpath):
                os.rmdir(dirpath)
                undo.append(f'mkdir -p -- "{rel(dirpath)}"')
                flush()
        except OSError:
            pass
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"map_absolute_episodes.py --apply  ({date})\nShow: {show_dir}\n")
        fh.write(f"files moved: {moved}\n\n" + "\n".join(loglines) + "\n")
    print(f"APPLIED: {moved} files moved.\n  log:  {log_path}\n  undo: {undo_path}")


def main(argv=None):
    _require_py311()
    ap = argparse.ArgumentParser(description="Map an absolute-numbered show to Plex via TheTVDB.")
    ap.add_argument("dir", help="the show directory")
    ap.add_argument("--name", help="series name to search (default: cleaned folder name)")
    ap.add_argument("--tvdb-id", help="use this TheTVDB series id, skip search")
    ap.add_argument("--order", default="default",
                    help="episode order to read absolute numbers from (default: default)")
    ap.add_argument("--offline", action="store_true",
                    help="only show parsed absolute numbers; no network")
    ap.add_argument("--apply", action="store_true", help="perform renames (logged + reversible)")
    ap.add_argument("--log-dir", help="where logs/undo go (default: parent of DIR)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.dir):
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    show_dir = os.path.abspath(args.dir)
    if args.name:
        label, folder_year = args.name, None
    else:
        label, folder_year = clean_name(os.path.basename(show_dir))

    files = list(collect(show_dir))
    if args.offline:
        print(f"OFFLINE parse of {show_dir}\n  search name would be: {label}\n")
        for rel, absn, _ in files:
            print(f"  abs={absn if absn is not None else '?':>3}  {rel}")
        miss = sum(1 for _, a, _ in files if a is None)
        print(f"\n{len(files)} files, {miss} without a clear absolute number.")
        return 0

    api_key = _cfg("FIELDKIT_TVDB_API_KEY")
    if not api_key:
        print("error: FIELDKIT_TVDB_API_KEY not set. Add it to the repo .env "
              "(see example.env) or the environment. Get a key at "
              "https://thetvdb.com/dashboard.", file=sys.stderr)
        return 4
    series_year = None
    try:
        token = tvdb_login(api_key, _cfg("FIELDKIT_TVDB_PIN"))
        if args.tvdb_id:
            series_id, series_year = args.tvdb_id, None
            print(f"using TheTVDB series id {series_id}")
        else:
            hits = tvdb_search(token, label)
            if not hits:
                print(f"no TheTVDB series match for '{label}'. Try --name or --tvdb-id.",
                      file=sys.stderr)
                return 4
            top = hits[0]
            if folder_year:  # prefer the hit whose year matches the folder
                top = next((h for h in hits if str(h.get("year")) == str(folder_year)), top)
            series_id = top.get("tvdb_id") or top.get("id", "").split("-")[-1]
            series_year = top.get("year") or folder_year
            print(f"matched: {top.get('name')} ({series_year})  tvdb_id={series_id}")
            print("  (verify this is correct; use --tvdb-id to override)\n")
        ep_map = tvdb_episode_map(token, series_id, args.order)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, ValueError) as exc:
        print(f"error: TheTVDB lookup failed: {exc}", file=sys.stderr)
        return 4

    moves, unparsed, unmapped = plan_renames(show_dir, label, series_year, ep_map)
    print(f"PLAN for {os.path.basename(show_dir)}  ({len(ep_map)} TVDB episodes, "
          f"{len(moves)} mappable files)")
    for rel_src, rel_dst in moves[:8]:
        print(f"  {rel_src}\n    -> {rel_dst}")
    if len(moves) > 8:
        print(f"  ... and {len(moves) - 8} more")
    if unparsed:
        print(f"\n  {len(unparsed)} file(s) with no clear absolute number (left in place):")
        for rel in unparsed[:5]:
            print(f"    ? {rel}")
    if unmapped:
        print(f"\n  {len(unmapped)} file(s) whose absolute number is not in TheTVDB (left in place):")
        for rel, absn in unmapped[:5]:
            print(f"    ! abs {absn}: {rel}")

    if args.apply:
        log_dir = os.path.abspath(args.log_dir) if args.log_dir else os.path.dirname(show_dir)
        do_apply(show_dir, moves, log_dir, datetime.date.today().isoformat())
    else:
        print("\nPREVIEW only — re-run with --apply to perform the renames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
