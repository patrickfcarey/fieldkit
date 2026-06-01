# Name: normalize_movies.py
# Description: Normalize a "Title (Year)" movie library toward a clean Plex layout. Four steps:
#                strip-tags  - drop release junk from folder names -> "Title (Year)"
#                fold-loose  - move loose video files into "Title (Year)/Title (Year).ext"
#                dedupe      - resolve duplicate "Title (Year)" groups KEEP-LARGEST,
#                              quarantining (never deleting) the smaller copies
#                editions    - reformat edition/cut folders -> "Title (Year) {edition-...}"
#              DRY-RUN by default; pass --apply to make changes. Every applied step writes a
#              log and a reversible undo .sh; dedupe moves losers to a dated quarantine folder.
# Usage: python3.11 normalize_movies.py DIR [--step {strip-tags,fold-loose,dedupe,editions,all}]
#                                            [--apply] [--log-dir DIR] [--protect "Title (Year)"]
# Inputs: A movie library directory
# Outputs: Plan to stdout; on --apply also <log-dir>/normalize-STEP-DATE.log,
#          <log-dir>/undo-STEP-DATE.sh, and (dedupe) <log-dir>/_duplicates-DATE/
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
#   - Movies are named "Title (YYYY)"; DIR and --log-dir are on the SAME filesystem as the
#     library so moves are atomic renames (instant, no copy).
# Failure Modes:
#   - DIR not a directory (exits 2).
#   - A target name already exists -> that single action is skipped and logged, never clobbered.
# Notes:
#   - A trailing "{edition-...}" tag is treated as part of a film's identity, NOT as junk:
#     a film and its edition are never merged as duplicates, and the tag is preserved.
#   - dedupe deletes nothing; review the quarantine folder, then remove it yourself.
#   - editions skips titles where the keyword is part of the real name; use --protect to add more.

import argparse
import datetime
import os
import re
import sys

VIDEO_EXTS = {
    ".avi", ".mp4", ".mkv", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg",
    ".flv", ".ts", ".webm", ".iso", ".divx",
}
YEAR = re.compile(r"\((?:19|20)\d{2}\)")
EDITION_TAG = re.compile(r"\s*\{edition-[^}]*\}\s*$")
# strong edition signals only (avoids ambiguous bare words like "Cut" / "Uncut")
EDITION_PATTERNS = [
    (re.compile(r"director'?s cut", re.I), "Director's Cut"),
    (re.compile(r"extended cut", re.I), "Extended Cut"),
    (re.compile(r"final cut", re.I), "Final Cut"),
    (re.compile(r"extended edition", re.I), "Extended Edition"),
    (re.compile(r"ultimate edition", re.I), "Ultimate Edition"),
    (re.compile(r"special edition", re.I), "Special Edition"),
    (re.compile(r"theatrical cut", re.I), "Theatrical Cut"),
    (re.compile(r"\bextended\b", re.I), "Extended"),
    (re.compile(r"\bunrated\b", re.I), "Unrated"),
    (re.compile(r"remaster(?:ed)?", re.I), "Remastered"),
    (re.compile(r"\btheatrical\b", re.I), "Theatrical"),
    (re.compile(r"\bredux\b", re.I), "Redux"),
    (re.compile(r"\brecut\b", re.I), "Recut"),
    (re.compile(r"\bimax\b", re.I), "IMAX"),
]


def split_components(name):
    """Return (title_year, edition_tag_or_None, trailing_junk).

    A trailing '{edition-...}' tag is split off first and preserved. 'title_year' is the text
    up to and including the LAST (YYYY) token in the remainder; 'trailing_junk' is whatever sat
    between that year and the edition tag (the part safe to strip). title_year is None if no year.
    """
    m = EDITION_TAG.search(name)
    edition = name[m.start():].strip() if m else None
    base = name[: m.start()].rstrip() if m else name
    years = list(YEAR.finditer(base))
    if not years:
        return None, edition, ""
    end = years[-1].end()
    return base[:end].strip(), edition, base[end:].strip(" .-_[](){}")


def canonical_name(name):
    """Clean identity of an entry: 'Title (Year)' plus any '{edition-...}' tag. None if no year."""
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


def size_of(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def canon_map_of(root):
    """Map canonical identity -> [entry names]. Folders and loose video files both count."""
    cmap = {}
    for e in os.listdir(root):
        if e.endswith("Zone.Identifier") or e.startswith("."):
            continue
        full = os.path.join(root, e)
        if os.path.isdir(full):
            canon = canonical_name(e)
        else:
            stem, ext = os.path.splitext(e)
            if ext.lower() not in VIDEO_EXTS:
                continue
            canon = canonical_name(stem)
        if canon:
            cmap.setdefault(canon, []).append(e)
    return cmap


def has_edition_keyword(text):
    return any(rx.search(text) for rx, _ in EDITION_PATTERNS)


class Runner:
    """Collects planned actions, applies them when apply=True, and records undo lines."""

    def __init__(self, root, step, log_dir, date, apply):
        self.root = root
        self.step = step
        self.log_dir = log_dir
        self.date = date
        self.apply = apply
        self.actions = []
        self.undo = []

    def move(self, src_rel, dst_abs, undo_cmds):
        src = os.path.join(self.root, src_rel)
        if os.path.exists(dst_abs):
            self.actions.append(f"  SKIP (target exists): {src_rel}")
            return False
        if self.apply:
            os.rename(src, dst_abs)
            self.undo.extend(undo_cmds)
        return True

    def write_logs(self):
        if not self.apply:
            return None, None
        os.makedirs(self.log_dir, exist_ok=True)
        log = os.path.join(self.log_dir, f"normalize-{self.step}-{self.date}.log")
        undo = os.path.join(self.log_dir, f"undo-{self.step}-{self.date}.sh")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(f"normalize_movies.py --step {self.step}  ({self.date})\nSource: {self.root}\n\n")
            fh.write("\n".join(self.actions) + "\n")
        with open(undo, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\nset -euo pipefail\n")
            fh.write(f'cd "{self.root}"\n')
            fh.write("\n".join(self.undo) + "\n")
        os.chmod(undo, 0o755)
        return log, undo


def step_strip_tags(r, cmap):
    for e in sorted(os.listdir(r.root), key=str.lower):
        full = os.path.join(r.root, e)
        if e.startswith(".") or not os.path.isdir(full):
            continue
        canon = canonical_name(e)
        if not canon or canon == e:
            continue
        _, _, junk = split_components(e)
        if junk and has_edition_keyword(junk):
            r.actions.append(f"  defer to editions: {e}")
            continue
        if len(cmap.get(canon, [])) > 1:
            r.actions.append(f"  defer to dedupe (dup): {e}")
            continue
        if r.move(e, os.path.join(r.root, canon), [f'mv -n -- "{canon}" "{e}"']):
            r.actions.append(f"  {e}\n    -> {canon}")


def step_fold_loose(r, cmap):
    for e in sorted(os.listdir(r.root), key=str.lower):
        full = os.path.join(r.root, e)
        if e.startswith(".") or os.path.isdir(full):
            continue
        stem, ext = os.path.splitext(e)
        ext = ext.lower()
        if ext not in VIDEO_EXTS:
            continue
        canon = canonical_name(stem)
        if not canon:
            continue
        if len(cmap.get(canon, [])) > 1:
            r.actions.append(f"  defer to dedupe (dup): {e}")
            continue
        target_dir = os.path.join(r.root, canon)
        if os.path.exists(target_dir):
            r.actions.append(f"  SKIP (folder exists): {e}")
            continue
        if r.apply:
            os.mkdir(target_dir)
            os.rename(full, os.path.join(target_dir, f"{canon}{ext}"))
            r.undo.append(f'mv -n -- "{canon}/{canon}{ext}" "{e}"')
            r.undo.append(f'rmdir -- "{canon}"')
        r.actions.append(f"  {e}\n    -> {canon}/{canon}{ext}")


def step_dedupe(r, cmap):
    quar = os.path.join(r.log_dir, f"_duplicates-{r.date}")
    groups = {c: v for c, v in cmap.items() if len(v) > 1}
    if r.apply and groups:
        os.makedirs(quar, exist_ok=True)
    for canon in sorted(groups, key=str.lower):
        members = []
        for name in groups[canon]:
            full = os.path.join(r.root, name)
            members.append((name, full, os.path.isdir(full), size_of(full)))
        members.sort(key=lambda m: (m[3], m[0] == canon, m[2]), reverse=True)
        keeper = members[0]
        r.actions.append(f"  {canon}")
        r.actions.append(f"    KEEP       [{'dir ' if keeper[2] else 'file'}] {keeper[0]}  ({human(keeper[3])})")
        for name, full, isdir, sz in members[1:]:
            dst = os.path.join(quar, name)
            i = 2
            while os.path.exists(dst):
                dst = os.path.join(quar, f"{name} (dup{i})")
                i += 1
            if r.apply:
                os.rename(full, dst)
                r.undo.append(f'mv -n -- "{dst}" "{os.path.join(r.root, name)}"')
            r.actions.append(f"    QUARANTINE [{'dir ' if isdir else 'file'}] {name}  ({human(sz)})")
        kname, kfull, kisdir, _ = keeper
        if not kisdir:
            ext = os.path.splitext(kname)[1].lower()
            newdir = os.path.join(r.root, canon)
            if not os.path.exists(newdir):
                if r.apply:
                    os.mkdir(newdir)
                    os.rename(kfull, os.path.join(newdir, f"{canon}{ext}"))
                    r.undo.append(f'mv -n -- "{canon}/{canon}{ext}" "{kname}"')
                    r.undo.append(f'rmdir -- "{canon}"')
                r.actions.append(f"    -> foldered keeper to {canon}/{canon}{ext}")
        elif kname != canon and not os.path.exists(os.path.join(r.root, canon)):
            if r.apply:
                os.rename(kfull, os.path.join(r.root, canon))
                r.undo.append(f'mv -n -- "{canon}" "{kname}"')
            r.actions.append(f"    -> renamed keeper to {canon}")
        r.actions.append("")


def detect_edition(name):
    for rx, label in EDITION_PATTERNS:
        m = rx.search(name)
        if m:
            return rx, label
    return None, None


def step_editions(r, cmap, protect):
    for e in sorted(os.listdir(r.root), key=str.lower):
        full = os.path.join(r.root, e)
        if e.startswith(".") or not os.path.isdir(full) or e in protect:
            continue
        if "{edition-" in e:
            continue  # already normalized
        rx, label = detect_edition(e)
        if not rx:
            continue
        years = list(YEAR.finditer(e))
        if not years:
            continue
        last = years[-1]
        before = e[: last.start()].strip()
        year = e[last.start(): last.end()]
        title = re.sub(r"\s{2,}", " ", rx.sub("", before).strip(" -._"))
        if not title:
            r.actions.append(f"  SKIP (no title left, likely false positive): {e}")
            continue
        new = f"{title} {year} {{edition-{label}}}"
        if r.move(e, os.path.join(r.root, new), [f'mv -n -- "{new}" "{e}"']):
            r.actions.append(f"  {e}\n    -> {new}")


STEPS = ["strip-tags", "fold-loose", "dedupe", "editions"]


def run_step(root, step, log_dir, date, apply, protect):
    r = Runner(root, step, log_dir, date, apply)
    cmap = canon_map_of(root)
    if step == "strip-tags":
        step_strip_tags(r, cmap)
    elif step == "fold-loose":
        step_fold_loose(r, cmap)
    elif step == "dedupe":
        step_dedupe(r, cmap)
    elif step == "editions":
        step_editions(r, cmap, protect)
    print(f"== step: {step}  ({'APPLY' if apply else 'DRY-RUN'}) ==")
    print("\n".join(r.actions) if r.actions else "  (nothing to do)")
    log, undo = r.write_logs()
    if log:
        print(f"  log:  {log}\n  undo: {undo}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Normalize a Title (Year) movie library (dry-run by default).")
    ap.add_argument("dir")
    ap.add_argument("--step", choices=STEPS + ["all"], default="all")
    ap.add_argument("--apply", action="store_true", help="make changes (default: dry-run)")
    ap.add_argument("--log-dir", help="where logs/undo/quarantine go (default: parent of DIR)")
    ap.add_argument("--protect", action="append", default=[],
                    help="folder name to never treat as an edition (repeatable)")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.dir):
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    root = os.path.abspath(args.dir)
    log_dir = os.path.abspath(args.log_dir) if args.log_dir else os.path.dirname(root)
    date = datetime.date.today().isoformat()
    steps = STEPS if args.step == "all" else [args.step]
    for step in steps:
        run_step(root, step, log_dir, date, args.apply, set(args.protect))
    if not args.apply:
        print("DRY-RUN only — no changes made. Re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
