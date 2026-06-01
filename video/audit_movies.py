# Name: audit_movies.py
# Description: Read-only audit of a movie library that uses the "Title (Year)" convention.
#              Reports release-junk tags in names, loose video files not in their own folder,
#              duplicate/collision groups (with sizes), edition/cut variants, junk/incomplete
#              files, and entries with no parseable year. Makes NO changes.
# Usage: python3.11 audit_movies.py DIR [--out FILE]
# Inputs: A directory whose children are movie folders and/or loose movie files
# Outputs: A normalization plan/report to stdout (or to --out FILE)
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
#   - Movies are named "Title (YYYY)" possibly followed by release junk and/or a
#     "{edition-...}" tag. UTF-8 filenames.
# Failure Modes:
#   - DIR does not exist (reported).
# Notes:
#   - Pairs with normalize_movies.py, which applies the changes this report describes.
#   - A trailing "{edition-...}" tag is part of identity, not junk: a film and its edition are
#     NOT reported as duplicates of each other.

import argparse
import os
import re
import sys

VIDEO_EXTS = {
    ".avi", ".mp4", ".mkv", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg",
    ".flv", ".ts", ".webm", ".iso", ".divx",
}
YEAR = re.compile(r"\((?:19|20)\d{2}\)")
EDITION_TAG = re.compile(r"\s*\{edition-[^}]*\}\s*$")
EDITION = re.compile(
    r"\b(Director'?s Cut|Final Cut|Extended(?: Cut| Edition)?|Unrated|Remaster(?:ed)?|"
    r"Theatrical|Special Edition|Ultimate Edition|Redux|IMAX|Recut)\b",
    re.I,
)


def split_components(name):
    """Return (title_year, edition_tag_or_None, trailing_junk); title_year None if no year."""
    m = EDITION_TAG.search(name)
    edition = name[m.start():].strip() if m else None
    base = name[: m.start()].rstrip() if m else name
    years = list(YEAR.finditer(base))
    if not years:
        return None, edition, ""
    end = years[-1].end()
    return base[:end].strip(), edition, base[end:].strip(" .-_[](){}")


def canonical_name(name):
    title_year, edition, _ = split_components(name)
    if title_year is None:
        return None
    return f"{title_year} {edition}" if edition else title_year


def human(num):
    num = float(num)
    for unit in ("B", "K", "M", "G", "T"):
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}P"


def dir_size(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def build_report(root):
    entries = [e for e in os.listdir(root) if not e.endswith("Zone.Identifier")]
    renames, loose, editions, junk, no_year = [], [], [], [], []
    canon_map = {}

    for e in sorted(entries, key=str.lower):
        full = os.path.join(root, e)
        if e.startswith("."):
            junk.append((e, "hidden / incomplete download"))
            continue
        if os.path.isdir(full):
            canon = canonical_name(e)
            if canon is None:
                no_year.append(e + "  [FOLDER]")
                continue
            canon_map.setdefault(canon, []).append(("folder", e))
            _, _, tail = split_components(e)
            already_edition = "{edition-" in e
            if not already_edition and EDITION.search(e):
                editions.append(e)
            elif canon != e:
                renames.append((e, canon, tail))
        else:
            stem, ext = os.path.splitext(e)
            ext = ext.lower()
            if ext not in VIDEO_EXTS:
                junk.append((e, f"non-video loose file ({ext or 'no ext'})"))
                continue
            canon = canonical_name(stem)
            if canon is None:
                no_year.append(e + "  [FILE]")
                continue
            canon_map.setdefault(canon, []).append(("file", e))
            loose.append((e, canon, ext))

    dups = {c: v for c, v in canon_map.items() if len(v) > 1}
    avi_loose = sum(1 for (_, _, ext) in loose if ext == ".avi")

    out = []
    w = out.append
    w("MOVIE NORMALIZATION AUDIT (read-only)")
    w(f"  Source: {root}\n")
    w("SUMMARY")
    w(f"  Entries scanned:            {len(entries)}")
    w(f"  Junk-tag folder renames:    {len(renames)}")
    w(f"  Loose files -> own folder:  {len(loose)}")
    w(f"  Duplicate/collision groups: {len(dups)}")
    w(f"  Edition/version to review:  {len(editions)}")
    w(f"  Junk / incomplete files:    {len(junk)}")
    w(f"  Entries with no (Year):     {len(no_year)}")
    w(f"  .avi loose files (SD upgrade candidates): {avi_loose}\n")

    w("1) FOLDER RENAMES (strip release junk)")
    for orig, canon, tail in renames:
        w(f"  {orig}\n    -> {canon}" + (f"   [drop: {tail}]" if tail else ""))
    w("\n2) LOOSE FILES -> OWN FOLDER")
    for f, canon, ext in loose:
        w(f"  {f}\n    -> {canon}/{canon}{ext}")
    w("\n3) DUPLICATES / COLLISIONS (nothing auto-merged)")
    for canon in sorted(dups, key=str.lower):
        w(f"  {canon}")
        for typ, orig in dups[canon]:
            p = os.path.join(root, orig)
            try:
                sz = human(dir_size(p) if typ == "folder" else os.path.getsize(p))
            except OSError:
                sz = "?"
            w(f"      [{typ:6}] {orig}   ({sz})")
    w("\n4) EDITION / VERSION (review; reformat to {edition-...})")
    for orig in editions:
        w(f"  {orig}")
    w("\n5) JUNK / INCOMPLETE / NON-VIDEO")
    for f, reason in junk:
        w(f"  {f}    <- {reason}")
    w("\n6) NO (YEAR) PARSED")
    for n in no_year:
        w(f"  {n}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only audit of a Title (Year) movie library.")
    ap.add_argument("dir", help="movie library directory")
    ap.add_argument("--out", help="write report to this file instead of stdout")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.dir):
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    report = build_report(args.dir)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
