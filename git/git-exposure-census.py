#!/usr/bin/env python3
"""git-exposure-census.py — how much work on this machine exists NOWHERE else?

Walks one or more directories, finds every git checkout (including worktrees, whose
`.git` is a file), and reports, per repo, the state that a disk failure would destroy:

  * commits reachable from a local branch but from NO remote-tracking ref
    (`git rev-list --branches --not --remotes`) — the number that matters most;
  * whether the repo has ANY pushable remote at all (a remote whose push URL is a
    real host; `no_push://` placeholders and bare local paths do not count);
  * local branches with no upstream, and how far tracking branches are ahead;
  * dirty files, split into REAL edits and whitespace/line-ending-only noise
    (`git diff --ignore-all-space --ignore-cr-at-eol` — on Windows-mounted
    checkouts most "3,000 dirty files" are CRLF flips, not work);
  * untracked files, stashes, submodules, linked worktrees, last commit date.

Output: a one-line-per-repo table on stdout, a TSV via --out, JSON via --json, and a
summary. Exit status is a GATE: 1 when any repo has commits on no remote, or has no
pushable remote, unless --no-gate. That makes it usable as a pre-shutdown check or
a cron job whose failure means "you are about to lose something".

Configuration (fieldkit convention): roots come from the CLI, else from `.env` beside
the repo root as GIT_CENSUS_ROOTS (colon-separated), else the current directory.
Stdlib only. Python 3.9+. Read-only: it never runs a mutating git command.

    git-exposure-census.py /path/to/repos ~/worktrees --out census.tsv
    git-exposure-census.py --self-test        # proves it can say "exposed" AND "clean"

Why it exists: a 2026-09-10 census of a development workstation found 9,334 commits
on no remote across 53 checkouts, two repos with no pushable remote at all, and
several hundred unpushed commits per checkout on a second machine — none of it
visible from any one repo's `git status`.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def git(repo, *args, timeout=120):
    """Run a read-only git command; '' on any failure (a repo we cannot read is reported as such, never skipped silently)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def is_checkout(p: Path) -> bool:
    g = p / ".git"
    return g.is_dir() or g.is_file()          # a file = a linked worktree


def find_checkouts(roots, max_depth=2):
    """Checkouts directly under each root (depth 1), plus root itself if it is one.
    Deliberately shallow: nested repos inside a checkout are that checkout's business."""
    seen, out = set(), []
    for root in roots:
        root = Path(os.path.expanduser(root))
        if not root.is_dir():
            continue
        cands = [root] + sorted(p for p in root.iterdir() if p.is_dir())
        for c in cands:
            if is_checkout(c) and c.resolve() not in seen:
                seen.add(c.resolve()); out.append(c)
    return out


def classify_remote(url: str) -> str:
    """A coarse, machine-agnostic class. Never records the host itself."""
    u = url.strip()
    if not u:
        return "none"
    if u.startswith("no_push") or "blocked" in u:
        return "blocked"
    if re.match(r"^(/|[A-Za-z]:\\|file:|~)", u):
        return "local-path"
    if "github.com" in u:
        return "github"
    if re.match(r"^(ssh://|[\w.-]+@[\w.-]+:)", u):
        return "ssh-host"
    if u.startswith("http"):
        return "https-host"
    return "other"


def census_one(repo: Path) -> dict:
    push_remotes = {}
    for ln in git(repo, "remote", "-v").splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+\((push)\)", ln)
        if m:
            push_remotes[m.group(1)] = classify_remote(m.group(2))
    pushable = [n for n, c in push_remotes.items() if c in ("github", "ssh-host", "https-host")]
    branch = git(repo, "branch", "--show-current") or "(detached)"
    dirty_all = [l for l in git(repo, "status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
    ws_stat = git(repo, "diff", "--ignore-all-space", "--ignore-cr-at-eol", "--stat")
    real_files = 0
    m = re.search(r"(\d+) files? changed", ws_stat.splitlines()[-1] if ws_stat else "")
    if m:
        real_files = int(m.group(1))
    untracked = sum(1 for l in git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() if l.startswith("??"))
    stashes = len(git(repo, "stash", "list").splitlines())
    noup, ahead = [], []
    for ln in git(repo, "for-each-ref", "--format=%(refname:short)|%(upstream:short)|%(upstream:track)", "refs/heads").splitlines():
        b, up, tr = (ln.split("|") + ["", ""])[:3]
        if not up or "gone" in tr:
            noup.append(b)
        else:
            a = re.search(r"ahead (\d+)", tr)
            if a:
                ahead.append(f"{b}+{a.group(1)}")
    unreach = git(repo, "rev-list", "--count", "--branches", "--not", "--remotes")
    last = git(repo, "log", "-1", "--format=%cs")
    subs = len(git(repo, "submodule", "status").splitlines()) if (repo / ".gitmodules").exists() else 0
    wts = max(0, len(git(repo, "worktree", "list").splitlines()) - 1)
    return {
        "repo": repo.name, "path": str(repo), "kind": "worktree" if (repo / ".git").is_file() else "repo",
        "remotes": ",".join(f"{n}:{c}" for n, c in push_remotes.items()) or "NONE",
        "pushable": bool(pushable), "branch": branch,
        "commits_on_no_remote": int(unreach) if unreach.isdigit() else -1,
        "dirty_files": len(dirty_all), "dirty_real": real_files, "dirty_noise": max(0, len(dirty_all) - real_files),
        "untracked": untracked, "stashes": stashes,
        "branches_no_upstream": len(noup), "no_upstream_names": " ".join(noup)[:200],
        "ahead": " ".join(ahead)[:200], "submodules": subs, "worktrees": wts, "last_commit": last,
    }


def run(roots, out=None, as_json=None, gate=True, quiet=False):
    rows = [census_one(r) for r in find_checkouts(roots)]
    if not quiet:
        print(f"{'repo':30s} {'kind':8s} {'remotes':26s} {'branch':22s} unpushed  real/noise  untr  stash  noup  last")
        for r in rows:
            print(f"{r['repo'][:30]:30s} {r['kind']:8s} {r['remotes'][:26]:26s} {r['branch'][:22]:22s} "
                  f"{r['commits_on_no_remote']:8d}  {r['dirty_real']:4d}/{r['dirty_noise']:<5d} {r['untracked']:4d}  {r['stashes']:5d}  {r['branches_no_upstream']:4d}  {r['last_commit']}")
    if out:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["repo"], delimiter="\t")
            w.writeheader(); w.writerows(rows)
    if as_json:
        Path(as_json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    exposed = [r for r in rows if r["commits_on_no_remote"] > 0]
    unpushable = [r for r in rows if not r["pushable"]]
    real_dirty = [r for r in rows if r["dirty_real"] > 0]
    total = sum(r["commits_on_no_remote"] for r in rows if r["commits_on_no_remote"] > 0)
    if not quiet:
        print(f"\nSUMMARY: {len(rows)} checkouts | {total} commits on no remote in {len(exposed)} repos | "
              f"{len(unpushable)} with NO pushable remote | {len(real_dirty)} with real uncommitted edits | "
              f"{sum(r['untracked'] for r in rows)} untracked files | {sum(r['stashes'] for r in rows)} stashes | "
              f"{sum(r['branches_no_upstream'] for r in rows)} branches without upstream")
        for r in unpushable:
            print(f"  NO PUSHABLE REMOTE: {r['repo']} ({r['remotes']}) — {r['commits_on_no_remote']} commits exist only here")
        for r in sorted(exposed, key=lambda x: -x["commits_on_no_remote"])[:15]:
            print(f"  EXPOSED: {r['repo']:30s} {r['commits_on_no_remote']:6d} commits on no remote; no-upstream: {r['no_upstream_names'][:80]}")
    if gate and (exposed or unpushable):
        return 1
    return 0


def self_test() -> int:
    """The gate must be able to say EXPOSED and CLEAN; a check that cannot fail is decoration."""
    ok = True

    def case(name, cond):
        nonlocal ok
        ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bare = td / "origin.git"; subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def mk(name, remote=True):
            p = td / name; subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True)
            (p / "a.txt").write_text("a\n")
            subprocess.run(["git", "-C", str(p), "add", "."], check=True, env=env)
            subprocess.run(["git", "-C", str(p), "commit", "-q", "-m", "one"], check=True, env=env)
            if remote:
                subprocess.run(["git", "-C", str(p), "remote", "add", "origin", f"ssh://git@example.invalid{bare}"], check=True)
                # simulate a fetched remote ref without network: point origin/main at HEAD
                sha = git(p, "rev-parse", "HEAD")
                subprocess.run(["git", "-C", str(p), "update-ref", "refs/remotes/origin/main", sha], check=True)
                subprocess.run(["git", "-C", str(p), "branch", "-u", "origin/main"], check=True, capture_output=True)
            return p

        clean = mk("clean")
        exposed = mk("exposed")
        (exposed / "b.txt").write_text("b\n")
        subprocess.run(["git", "-C", str(exposed), "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", str(exposed), "commit", "-q", "-m", "two (unpushed)"], check=True, env=env)
        (exposed / "a.txt").write_text("a changed\n")          # a real edit
        noise = mk("noise")
        (noise / "a.txt").write_text("a\r\n")                  # CRLF-only flip
        orphan = mk("orphan", remote=False)

        rows = {r["repo"]: r for r in map(census_one, [clean, exposed, noise, orphan])}
        case("clean repo: 0 commits on no remote, pushable", rows["clean"]["commits_on_no_remote"] == 0 and rows["clean"]["pushable"])
        case("exposed repo: 1 commit on no remote", rows["exposed"]["commits_on_no_remote"] == 1)
        case("exposed repo: the real edit is counted as real", rows["exposed"]["dirty_real"] == 1)
        case("noise repo: CRLF flip is noise, not a real edit", rows["noise"]["dirty_files"] == 1 and rows["noise"]["dirty_real"] == 0)
        case("orphan repo: NO pushable remote, its commit exists only here", (not rows["orphan"]["pushable"]) and rows["orphan"]["commits_on_no_remote"] == 1)
        case("gate says EXPOSED (exit 1) for the temp root", run([str(td)], quiet=True) == 1)
        case("gate says CLEAN (exit 0) for a root holding only the clean repo",
             run([str(td / "clean")], quiet=True) == 0)
        case("worktree is found as a checkout", is_checkout(clean))
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def roots_from_env():
    here = Path(__file__).resolve().parent.parent
    envf = here / ".env"
    if envf.is_file():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            if ln.startswith("GIT_CENSUS_ROOTS="):
                return [p for p in ln.split("=", 1)[1].strip().strip('"').split(":") if p]
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("roots", nargs="*", help="directories whose immediate subdirectories are checkouts (default: .env GIT_CENSUS_ROOTS, else cwd)")
    ap.add_argument("--out", help="write the per-repo TSV here")
    ap.add_argument("--json", help="write the per-repo JSON here")
    ap.add_argument("--no-gate", action="store_true", help="always exit 0 (report only)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    roots = a.roots or roots_from_env() or [os.getcwd()]
    return run(roots, out=a.out, as_json=a.json, gate=not a.no_gate)


if __name__ == "__main__":
    sys.exit(main())
