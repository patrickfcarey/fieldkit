# Name: normalize_episodes.py
# Description: Plan (and optionally apply) a Plex-friendly layout for a TV/anime library:
#                Show (Year)/Season NN/Show - sNNeNN - Title.ext
#              For every show folder it cleans the show name, parses each episode's season and
#              episode number, and builds a rename plan. It is conservative: shows it cannot
#              confidently parse are FLAGGED, never guessed. Absolute-numbered anime (e.g.
#              "- 01 -", "ep 01") cannot be mapped to season/episode without a metadata lookup,
#              so they are flagged for manual handling. Shows split across multiple folders are
#              reported as merge candidates (merges are flagged, not auto-applied).
#              PREVIEW by default; --apply renames only the confidently MAPPABLE single-folder
#              shows, with a log and a reversible undo script.
# Usage: python3.11 normalize_episodes.py DIR [--out FILE] [--apply] [--log-dir DIR]
# Inputs: A directory whose immediate children are show folders
# Outputs: A preview plan to --out or stdout; on --apply also <log-dir>/normalize-episodes-DATE.log
#          and <log-dir>/undo-episodes-DATE.sh
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
#   - Immediate children of DIR are individual shows. Episodes may be flat in the show folder
#     or under "Season NN" subfolders. UTF-8 filenames. Same-filesystem moves.
# Failure Modes:
#   - DIR not a directory (exits 2).
#   - Show-name cleaning is heuristic; review the preview before --apply.
# Notes:
#   - --apply intentionally touches ONLY mappable single-folder shows. Merges, absolute-numbered,
#     mixed/unparsed, and miscategorized entries are reported but left untouched.

import argparse
import datetime
import os
import re
import sys

VIDEO_EXTS = {
    ".avi", ".mp4", ".mkv", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg",
    ".flv", ".ts", ".webm", ".ogm", ".rm", ".rmvb",
}
YEAR = re.compile(r"\((?:19|20)\d{2}\)")

SXXEXX = re.compile(r"[sS](\d{1,2})[ ._-]*[eE](\d{1,3})")
SEASON_WORD = re.compile(r"season[ ._-]*(\d{1,2}).*?episode[ ._-]*(\d{1,3})", re.I)
NXNN = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})[xX](\d{1,3})(?![0-9])")
EP_ONLY = re.compile(r"\b(?:ep|episode|session|e)[ ._-]*(\d{1,3})\b", re.I)
DASH_NUM = re.compile(r"[-–][ _]*(\d{1,3})[ _]*[-–]")
SEASON_DIR = re.compile(r"season[ ._-]*(\d{1,2})", re.I)
BARE_SEASON_DIR = re.compile(r"^0*(\d{1,2})$")

# tokens that mark the start of release junk in a show folder name
JUNK_CUT = re.compile(
    r"\b(season|s\d{1,2}(?:[ ._-]?-?[ ._-]?s?\d{1,2})?|complete|1080p|720p|480p|2160p|"
    r"x264|x265|hevc|bluray|web[ ._-]?dl|webrip|hdtv|dvdrip|dvd|aac|dts|repack|proper|xvid|divx)\b",
    re.I,
)
TITLE_JUNK = re.compile(
    r"\b(1080p|720p|480p|2160p|x264|x265|hevc|bluray|web[ ._-]?dl|webrip|hdtv|dvdrip|aac|dts|"
    r"repack|proper|ac3|bdrip|dual audio)\b",
    re.I,
)


def clean_show(folder):
    """Heuristically derive ('Show (Year)' or 'Show', year_or_None) from a messy folder name."""
    name = folder
    year_match = YEAR.search(name)
    cut = len(name)
    jm = JUNK_CUT.search(name)
    if jm:
        cut = jm.start()
    year = None
    if year_match and year_match.start() < cut:
        year = year_match.group(0)[1:-1]
        show = name[: year_match.end()]
    else:
        show = name[:cut]
    show = re.sub(r"^\[[^\]]*\]\s*", "", show)      # drop leading [group]
    show = show.replace(".", " ").replace("_", " ")
    show = re.sub(r"[ _-]+\d{1,3}(?:[ _-]+\d{1,3})?\s*$", "", show)  # trailing "1-26" episode range
    show = re.sub(r"\s{2,}", " ", show).strip(" -._")
    if year and f"({year})" not in show:
        show = f"{show} ({year})"
    return show, year


def season_hint(dirname):
    m = SEASON_DIR.search(dirname)
    if m:
        return int(m.group(1))
    m = BARE_SEASON_DIR.match(dirname.strip())
    if m:
        return int(m.group(1))
    return None


def parse_episode(fname, hint):
    """Return (season, episode, method) or None. season is None for absolute numbering."""
    m = SXXEXX.search(fname)
    if m:
        return int(m.group(1)), int(m.group(2)), "sxxexx", m.end()
    m = SEASON_WORD.search(fname)
    if m:
        return int(m.group(1)), int(m.group(2)), "seasonword", m.end()
    m = NXNN.search(fname)
    if m:
        return int(m.group(1)), int(m.group(2)), "nxnn", m.end()
    m = DASH_NUM.search(fname) or EP_ONLY.search(fname)
    if m:
        ep = int(m.group(1))
        if hint is not None:
            return hint, ep, "seasonfolder", m.end()
        return None, ep, "absolute", m.end()
    return None


def extract_title(fname, end_idx):
    rest = os.path.splitext(fname[end_idx:])[0]
    rest = re.sub(r"^[ ._\-]+", "", rest)
    rest = TITLE_JUNK.split(rest)[0]
    rest = re.sub(r"\[[^\]]*\]", "", rest)
    rest = rest.replace(".", " ").replace("_", " ").strip(" -._")
    rest = re.sub(r"\s{2,}", " ", rest)
    return rest if 1 < len(rest) <= 80 and not rest.isdigit() else ""


def is_video(name):
    return os.path.splitext(name)[1].lower() in VIDEO_EXTS


def collect_episodes(show_path):
    """Yield (rel_path, season, episode, method, title, ext) for each video file under show_path."""
    for dirpath, _, files in os.walk(show_path):
        hint = season_hint(os.path.basename(dirpath))
        for f in sorted(files):
            if f.endswith("Zone.Identifier") or not is_video(f):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), show_path)
            parsed = parse_episode(f, hint)
            ext = os.path.splitext(f)[1].lower()
            if parsed is None:
                yield rel, None, None, "none", "", ext
            else:
                season, ep, method, end = parsed
                yield rel, season, ep, method, extract_title(f, end), ext


def classify(show_folder, episodes):
    """Return (status, show_label, year). status in mappable/absolute/mixed/miscategorized/empty."""
    show, year = clean_show(show_folder)
    if not episodes:
        return "empty", show, year
    methods = [e[3] for e in episodes]
    mapped = [m for m in methods if m in ("sxxexx", "seasonword", "nxnn", "seasonfolder")]
    absolute = [m for m in methods if m == "absolute"]
    none = [m for m in methods if m == "none"]
    if len(episodes) == 1 and (absolute or none) and YEAR.search(show_folder):
        return "miscategorized", show, year
    if mapped and not absolute and len(none) <= max(1, len(episodes) // 10):
        return "mappable", show, year
    if absolute and len(absolute) >= len(mapped):
        return "absolute", show, year
    return "mixed", show, year


def target_path(show, season, ep, title, ext):
    base = re.sub(r"\s*\((?:19|20)\d{2}\)$", "", show)
    name = f"{base} - s{season:02d}e{ep:02d}"
    if title:
        name += f" - {title}"
    return f"{show}/Season {season:02d}/{name}{ext}"


def build_preview(root):
    shows = sorted(
        (e for e in os.listdir(root)
         if os.path.isdir(os.path.join(root, e)) and not e.startswith(".")),
        key=str.lower,
    )
    loose = sorted(e for e in os.listdir(root)
                   if not os.path.isdir(os.path.join(root, e))
                   and not e.endswith("Zone.Identifier") and is_video(e))

    by_status = {"mappable": [], "absolute": [], "mixed": [], "miscategorized": [], "empty": []}
    canon_groups = {}      # normalized key -> {"label": best show label, "folders": [...]}
    total_renames = 0

    for folder in shows:
        eps = list(collect_episodes(os.path.join(root, folder)))
        status, show, year = classify(folder, eps)
        by_status[status].append((folder, show, year, eps))
        key = norm_key(show)
        grp = canon_groups.setdefault(key, {"label": show, "folders": []})
        grp["folders"].append(folder)
        # prefer a label that carries a (Year) and is longest/most complete
        if YEAR.search(show) and not YEAR.search(grp["label"]):
            grp["label"] = show
        elif len(show) > len(grp["label"]) and not YEAR.search(grp["label"]):
            grp["label"] = show
        if status == "mappable":
            total_renames += sum(1 for e in eps if e[1] is not None)

    merges = {g["label"]: g["folders"] for g in canon_groups.values() if len(g["folders"]) > 1}

    out = []
    w = out.append
    w("TV/ANIME NORMALIZATION PREVIEW (read-only)")
    w(f"  Source: {root}")
    w(f"  Target layout: Show (Year)/Season NN/Show - sNNeNN - Title.ext\n")
    w("SUMMARY")
    w(f"  Show folders:                 {len(shows)}")
    w(f"  Mappable (safe to rename):    {len(by_status['mappable'])}  ({total_renames} episode files)")
    w(f"  FLAG absolute-numbered:       {len(by_status['absolute'])}  (need metadata lookup)")
    w(f"  FLAG mixed/unparsed:          {len(by_status['mixed'])}")
    w(f"  FLAG likely movie/special:    {len(by_status['miscategorized'])}")
    w(f"  Empty/no video:               {len(by_status['empty'])}")
    w(f"  Merge groups (split shows):   {len(merges)}")
    w(f"  Loose top-level video files:  {len(loose)}\n")

    w("=" * 78)
    w("MERGE GROUPS — same show across multiple folders (merge is FLAGGED, not auto-applied)")
    w("=" * 78)
    for show in sorted(merges, key=str.lower):
        w(f"  {show}")
        for f in merges[show]:
            w(f"      <- {f}")
    if not merges:
        w("  (none)")

    w("\n" + "=" * 78)
    w("MAPPABLE SHOWS — proposed renames (showing up to 4 sample episodes each)")
    w("=" * 78)
    for folder, show, year, eps in by_status["mappable"]:
        mapped_eps = [e for e in eps if e[1] is not None]
        unparsed = len(eps) - len(mapped_eps)
        note = f", {unparsed} unparsed left in place" if unparsed else ""
        w(f"  {folder}/   ->   {show}/   [{len(mapped_eps)} eps{note}]")
        for rel, season, ep, method, title, ext in mapped_eps[:4]:
            w(f"      {rel}")
            w(f"        -> {target_path(show, season, ep, title, ext)}")

    w("\n" + "=" * 78)
    w("FLAGGED — ABSOLUTE NUMBERING (cannot map to season/episode without metadata)")
    w("=" * 78)
    for folder, show, year, eps in by_status["absolute"]:
        sample = next((e[0] for e in eps), "")
        w(f"  {folder}/   [{len(eps)} files]   e.g. {sample}")
    if not by_status["absolute"]:
        w("  (none)")

    w("\n" + "=" * 78)
    w("FLAGGED — MIXED / UNPARSED (inconsistent or unrecognized episode naming)")
    w("=" * 78)
    for folder, show, year, eps in by_status["mixed"]:
        bad = [e[0] for e in eps if e[3] == "none"][:3]
        w(f"  {folder}/   [{len(eps)} files]")
        for b in bad:
            w(f"        ? {b}")
    if not by_status["mixed"]:
        w("  (none)")

    w("\n" + "=" * 78)
    w("FLAGGED — LIKELY MOVIE/SPECIAL miscategorized as a show")
    w("=" * 78)
    for folder, show, year, eps in by_status["miscategorized"]:
        w(f"  {folder}/   e.g. {eps[0][0] if eps else ''}")
    if not by_status["miscategorized"]:
        w("  (none)")

    if loose:
        w("\n" + "=" * 78)
        w("LOOSE TOP-LEVEL VIDEO FILES (no show folder)")
        w("=" * 78)
        for f in loose:
            w(f"  {f}")
    return "\n".join(out) + "\n"


def norm_key(show):
    return re.sub(r"\s*\((?:19|20)\d{2}\)$", "", show).casefold().strip()


def apply_mappable(root, log_dir, date):
    """Apply renames for MAPPABLE shows that are NOT part of a merge group. Reversible.

    Per show: rename the folder to the clean label, move each parsed episode into
    'Season NN/Show - sNNeNN - Title.ext', leave unparsed files in place, prune emptied
    subfolders. Skips merge-group members, flagged shows, and any name collision.
    """
    folders = sorted(
        (e for e in os.listdir(root)
         if os.path.isdir(os.path.join(root, e)) and not e.startswith(".")),
        key=str.lower,
    )
    groups = {}
    info = []
    for folder in folders:
        eps = list(collect_episodes(os.path.join(root, folder)))
        status, show, year = classify(folder, eps)
        info.append((folder, show, status, eps))
        groups.setdefault(norm_key(show), []).append(folder)
    merge_keys = {k for k, v in groups.items() if len(v) > 1}

    rel = lambda p: os.path.relpath(p, root)
    undo = []          # appended in forward order; written REVERSED
    log = []
    moved = 0
    applied = 0
    skipped = {"flagged": 0, "merge": 0, "collision": 0, "noop": 0}

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"normalize-episodes-{date}.log")
    undo_path = os.path.join(log_dir, f"undo-episodes-{date}.sh")

    def flush_undo():
        # Rewrite the undo script after every change so a partial run is always reversible.
        # Best-effort (no 'set -e'): tolerates paths a partial run never created.
        with open(undo_path, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\n# Reverse normalize_episodes.py --apply (best-effort).\n")
            fh.write(f'cd "{root}"\n')
            fh.write("\n".join(reversed(undo)) + "\n")
        os.chmod(undo_path, 0o755)

    def record(line):
        undo.append(line)
        flush_undo()

    flush_undo()  # create the undo file up front, even before the first move

    for folder, show, status, eps in info:
        if status != "mappable":
            skipped["flagged"] += 1
            continue
        if norm_key(show) in merge_keys:
            skipped["merge"] += 1
            log.append(f"SKIP merge-group: {folder}")
            continue
        cur_dir = os.path.join(root, show if show == folder else folder)
        if show != folder:
            clean_dir = os.path.join(root, show)
            if os.path.exists(clean_dir):
                skipped["collision"] += 1
                log.append(f"SKIP folder collision: {folder} -> {show}")
                continue
            os.rename(cur_dir, clean_dir)
            record(f'mv -n -- "{show}" "{folder}"')
            log.append(f"RENAME folder: {folder} -> {show}")
            cur_dir = clean_dir
        applied += 1
        base = re.sub(r"\s*\((?:19|20)\d{2}\)$", "", show)
        for rel_path, season, ep, method, title, ext in eps:
            if season is None:
                continue
            src = os.path.join(cur_dir, rel_path)
            name = f"{base} - s{season:02d}e{ep:02d}" + (f" - {title}" if title else "") + ext
            dst = os.path.join(cur_dir, f"Season {season:02d}", name)
            if os.path.abspath(src) == os.path.abspath(dst):
                skipped["noop"] += 1
                continue
            if os.path.exists(dst):
                skipped["collision"] += 1
                log.append(f"  SKIP collision: {rel(dst)}")
                continue
            season_dir = os.path.dirname(dst)
            if not os.path.isdir(season_dir):
                os.makedirs(season_dir)
                record(f'rmdir -- "{rel(season_dir)}" 2>/dev/null || true')
            os.rename(src, dst)
            record(f'mv -n -- "{rel(dst)}" "{rel(src)}"')
            moved += 1
        # prune subfolders we emptied (old "Season 7" etc.); keep the show dir itself
        for dirpath, _, _ in os.walk(cur_dir, topdown=False):
            if dirpath == cur_dir:
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    record(f'mkdir -p -- "{rel(dirpath)}"')
            except OSError:
                pass

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"normalize_episodes.py --apply  ({date})\nSource: {root}\n\n")
        fh.write(f"shows changed: {applied} | files moved: {moved} | "
                 f"skipped: {skipped}\n\n")
        fh.write("\n".join(log) + "\n")
    flush_undo()
    print(f"APPLIED: {applied} shows changed, {moved} episode files moved.")
    print(f"skipped: {skipped['merge']} merge-group, {skipped['flagged']} flagged, "
          f"{skipped['collision']} collisions, {skipped['noop']} already-correct")
    print(f"log:  {log_path}")
    print(f"undo: {undo_path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Preview/plan a Plex TV/anime layout (read-only by default).")
    ap.add_argument("dir")
    ap.add_argument("--out", help="write preview to this file instead of stdout")
    ap.add_argument("--apply", action="store_true",
                    help="apply renames for mappable, non-merge shows (logged + reversible)")
    ap.add_argument("--log-dir", help="where logs/undo go on --apply (default: parent of DIR)")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.dir):
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    root = os.path.abspath(args.dir)
    if args.apply:
        log_dir = os.path.abspath(args.log_dir) if args.log_dir else os.path.dirname(root)
        return apply_mappable(root, log_dir, datetime.date.today().isoformat())
    report = build_preview(root)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
