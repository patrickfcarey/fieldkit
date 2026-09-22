#!/usr/bin/env python3
"""CI half of the fleet commit-identity guard -- the surface a local hook cannot reach.

WHY THIS EXISTS. The `commit-msg` hook installed fleet-wide on 2026-09-04 is a
LOCAL control: it runs on this machine, for commits made on this machine.
`docs/45-incidents-framework-apps.md` measures that **11 of the 15 identity
violations were committed off this machine, 7 of them by a cloud runner on a
`claude/*` branch in `loadout-pipeline-profiles`**. No local hook reaches any
of those, and `--no-verify` bypasses the ones it does reach. This runs on
GitHub's side of the wire, where neither escape exists.

Re-derived from git on 2026-09-04, not inherited from the doc -- union of
bad-identity and trailer commits over `--all`:

    loadout-pipeline-profiles   7   (7 bad identity, 6 of them also trailered)
    blitz-command               4   (1 bad identity, 3 trailer-only)
    fieldkit                    3   (trailer-only)
    pfc-hlds-template           1   (trailer-only)
                               --
                               15

======================================================================
THE PREDICATE IS NOT REWRITTEN. IT IS THE HOOK'S OWN.
======================================================================
This file loads ``commit-identity-predicate.py`` -- a byte-identical copy of
``experiments/fleet-hooks/identity/commit-msg`` -- and calls its ``decide()``.
Two implementations of one rule drift, and a CI check that disagreed with the
local hook would be worse than none: someone would learn to ignore whichever
one they met second. ``--verify-vendor`` asserts the copy still matches.

======================================================================
IT FAILS CLOSED. The hook it borrows from fails OPEN.
======================================================================
Deliberate, and the difference is the blast radius. A hook that wedges every
commit in 38 repos is worse than a wrong attribution, so ``commit-msg`` allows
anything it cannot evaluate. CI has no such cost: nothing is blocked but a
merge, and a check that passes when it could not evaluate the commits is the
"powerless check" this fleet keeps measuring. Any error -> non-zero.

Usage::

    check-commit-identity.py --range BASE..HEAD [--repo DIR]
    check-commit-identity.py --ci                 # range from the GitHub event
    check-commit-identity.py --self-test          # asserted case table
    check-commit-identity.py --verify-vendor      # predicate matches the hook
    check-commit-identity.py --stamp-vendor       # re-copy the hook and re-stamp

SCOPE, stated because a silent one would be a lie: this checks the commits in
the PUSH or PULL REQUEST it is given, not all of history. The 15 violations
above are already in these repos' history and are NOT retroactively failed by
this workflow -- rewriting them is a force-push decision that belongs to the
Architect (``~/.claude/CLAUDE.md``, "Recovery if you've already made bad-author
commits"). What this stops is the 16th.
"""

import hashlib
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREDICATE = os.path.join(HERE, "commit-identity-predicate.py")
#: the hook this predicate must stay byte-identical to. Present only beside the
#: canonical copy; a vendored .github/scripts/ copy has no hook next to it,
#: which is why the sha below exists.
HOOK = os.path.join(HERE, "commit-msg")

#: sha256 (newlines normalised) of the commit-msg hook this predicate was
#: vendored from. Stamped by --stamp-vendor.
#:
#: WITHOUT THIS the vendored copy had nothing to compare against and
#: --verify-vendor returned 0 unconditionally -- a step that could not fail,
#: which is the exact defect class this fleet keeps measuring (H-11). Caught
#: by running the vendored copy rather than reasoning about it.
PREDICATE_SHA256 = "734f2a2a451ab7764f848b358a9d6c20f52bf88f168c0a5a772a7c89c467ad9c"

REC, FLD = "\x01", "\x02"
FORMAT = REC + "%H" + FLD + "%an" + FLD + "%ae" + FLD + "%cn" + FLD + "%ce" + FLD + "%B"


def load_predicate(path=PREDICATE):
    if not os.path.isfile(path):
        raise RuntimeError("vendored predicate missing at %s -- this check "
                           "cannot evaluate anything and must not pass" % path)
    spec = importlib.util.spec_from_file_location("commit_identity_predicate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("decide", "check_message", "check_ident"):
        if not hasattr(mod, name):
            raise RuntimeError("vendored predicate has no %s(): it is not the "
                               "commit-msg hook" % name)
    return mod


def parse_log(text):
    """Pure. Raw `git log` output -> [(sha, an, ae, cn, ce, body)].

    Factored out so the whole walker is testable without making a single
    commit: the self-test feeds it captured log text.
    """
    out = []
    for rec in text.split(REC)[1:]:
        f = rec.split(FLD)
        if len(f) < 6:
            continue
        out.append((f[0], f[1], f[2], f[3], f[4], f[5]))
    return out


def violations(records, decide):
    """Pure. -> [(sha, subject, [reasons])] for every offending commit."""
    bad = []
    for sha, an, ae, cn, ce, body in records:
        ok, reasons = decide(body,
                             "%s <%s> 0 +0000" % (an, ae),
                             "%s <%s> 0 +0000" % (cn, ce))
        if not ok:
            bad.append((sha, body.splitlines()[0] if body.strip() else "<empty>",
                        reasons))
    return bad


def _resolves(rev, repo="."):
    return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q",
                           rev + "^{commit}"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def git_log(rev_args, repo="."):
    """rev_args is a LIST of git revision arguments, never a joined string."""
    args = ["git", "--no-optional-locks", "-C", repo, "log", "--no-merges",
            "--format=" + FORMAT] + list(rev_args)
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("git log %s failed: %s"
                           % (" ".join(rev_args),
                              p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout.decode("utf-8", "replace")


def ci_range(repo="."):
    """The revision arguments for the current GitHub event, as a LIST.

    Fails closed: an event shape it does not recognise raises rather than
    quietly checking nothing. Three shapes are handled explicitly, because each
    of the other two would otherwise degrade into a check that always passes
    or one that always fails:

      * pull_request        base..head
      * push, normal        before..after
      * push, new branch or FORCE-PUSH (before no longer resolves)
                            default-branch..after, else "commits unique to this
                            ref" (`after --not --all` minus this ref).

    The last fallback matters: falling back to ALL ancestors of `after` would
    re-flag the 15 violations already in these repos' history on every single
    push, and a check that is permanently red is a check nobody reads.
    """
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    if ev in ("pull_request", "pull_request_target"):
        base = os.environ.get("PR_BASE_SHA", "")
        head = os.environ.get("PR_HEAD_SHA", "")
        if not base or not head:
            raise RuntimeError("pull_request event without PR_BASE_SHA/PR_HEAD_SHA")
        return ["%s..%s" % (base, head)]
    if ev == "push":
        after = os.environ.get("PUSH_AFTER", "") or "HEAD"
        before = os.environ.get("PUSH_BEFORE", "")
        if before and set(before) != {"0"} and _resolves(before, repo):
            return ["%s..%s" % (before, after)]
        default = os.environ.get("DEFAULT_BRANCH", "")
        for ref in (["origin/" + default, default] if default else []):
            if _resolves(ref, repo):
                return ["%s..%s" % (ref, after)]
        ref = os.environ.get("GITHUB_REF", "")
        excl = ["--exclude=" + ref] if ref.startswith("refs/") else []
        return [after, "--not"] + excl + ["--all"]
    raise RuntimeError("unsupported event %r -- refusing to report a pass over "
                       "a range I could not determine" % ev)


def report(bad, total):
    ann = os.environ.get("GITHUB_ACTIONS") == "true"
    w = sys.stdout.write
    if not bad:
        w("commit-identity: %d commit(s) checked, none attributed to Claude.\n"
          % total)
        return 0
    for sha, subject, reasons in bad:
        for r in reasons:
            line = "%s (%s): %s" % (sha[:12], subject[:60], r)
            w(("::error title=Commit attributed to Claude::%s\n" % line) if ann
              else ("  x %s\n" % line))
    w("\n")
    w("commit-identity: %d of %d commit(s) violate the fleet identity rule.\n"
      % (len(bad), total))
    w("\n")
    w("  Never attribute a commit to Claude, on either surface: no trailer,\n")
    w("  and neither the AUTHOR nor the COMMITTER may be Claude. --author\n")
    w("  alone is NOT enough; the committer comes from config or the env.\n")
    w("\n")
    w('    GIT_COMMITTER_NAME="Patrick Carey" \\\n')
    w('    GIT_COMMITTER_EMAIL="patrickfcarey@gmail.com" \\\n')
    w('    git commit --author="Patrick Carey <patrickfcarey@gmail.com>" -m "..."\n')
    w("\n")
    w("  To fix commits already pushed on this branch (rewrites history):\n")
    w("    git rebase <base> --exec 'GIT_COMMITTER_NAME=\"Patrick Carey\" \\\n")
    w("      GIT_COMMITTER_EMAIL=\"patrickfcarey@gmail.com\" git commit \\\n")
    w("      --amend --no-edit --author=\"Patrick Carey "
      "<patrickfcarey@gmail.com>\"'\n")
    w("    then verify: git log --format='%h %an / %cn' -- both columns must\n")
    w("    show the real name.\n")
    return 1


# --- self-test ---------------------------------------------------------------

SELFTEST_LOG = (
    # sha, author name, author email, committer name, committer email, body
    "\x01" + "\x02".join(["a" * 40, "Patrick Carey", "patrickfcarey@gmail.com",
                          "Patrick Carey", "patrickfcarey@gmail.com",
                          "docs: a clean commit\n"]) +
    "\x01" + "\x02".join(["b" * 40, "Claude", "noreply@anthropic.com",
                          "Claude", "noreply@anthropic.com",
                          "rg-arc-d: add TODO-verify-paths.md\n"]) +
    "\x01" + "\x02".join(["c" * 40, "Claude Code", "patrickfcarey@gmail.com",
                          "Claude Code", "patrickfcarey@gmail.com",
                          "Complete Phase 8 Haiku tasks\n"]) +
    "\x01" + "\x02".join(["d" * 40, "pacarey", "patrickfcarey@gmail.com",
                          "pacarey", "patrickfcarey@gmail.com",
                          "feat: x\n\nCo-Authored-By: Claude Fable 5.1 "
                          "<noreply@anthropic.com>\n"]) +
    "\x01" + "\x02".join(["e" * 40, "Patrick Carey", "patrickfcarey@gmail.com",
                          "Claude Code", "patrickfcarey@gmail.com",
                          "the --author-alone trap\n"]) +
    "\x01" + "\x02".join(["f" * 40, "Patrick Carey", "patrickfcarey@gmail.com",
                          "Patrick Carey", "patrickfcarey@gmail.com",
                          "chore: strip the Co-Authored-By: Claude trailer "
                          "from the release script\n"]) +
    "\x01" + "\x02".join(["0" * 40, "Jean Claudel", "jc@example.org",
                          "Patrick Carey", "patrickfcarey@gmail.com",
                          "upstream cherry-pick\n"])
)


def self_test():
    fails = []

    def check(label, cond, detail=""):
        print("%s  %s" % ("PASS" if cond else "FAIL", label))
        if not cond:
            fails.append(label)
            if detail:
                print("        %s" % detail)

    try:
        mod = load_predicate()
    except Exception as exc:
        print("FAIL  the vendored predicate loads: %s" % exc)
        print("SELF-TEST FAILED")
        return 1
    check("the vendored predicate loads and exposes decide()", True)

    # The predicate's OWN case table must pass here too: if the hook's tests
    # fail, this check is built on sand and must say so before anything else.
    rc = subprocess.run([sys.executable, PREDICATE, "--self-test"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = rc.stdout.decode("utf-8", "replace").strip().splitlines()[-1:]
    check("the vendored predicate's own self-test passes (%s)"
          % (tail[0] if tail else "?"), rc.returncode == 0)

    recs = parse_log(SELFTEST_LOG)
    check("parse_log reads every record (7)", len(recs) == 7, "got %d" % len(recs))

    bad = violations(recs, mod.decide)
    got = {sha[0] for sha, _, _ in bad}
    check("the clean commit is not flagged", "a" not in got)
    check("both-identities-Claude (the 7 cloud-runner commits) is flagged",
          "b" in got)
    check("'Claude Code' with the real email (blitz-command) is flagged",
          "c" in got)
    check("trailer-only, human identity (fieldkit/pfc-hlds-template) is flagged",
          "d" in got)
    check("THE TRAP: --author fixed, committer still Claude Code, is flagged",
          "e" in got)
    check("MUST NOT FIRE: prose that discusses the trailer", "f" not in got)
    check("MUST NOT FIRE: a surname containing 'claude'", "0" not in got)
    check("exactly 4 of the 7 are violations", len(bad) == 4,
          "got %d: %s" % (len(bad), sorted(got)))

    # A check that cannot fail is the thing this fleet keeps being burned by.
    check("report() exits 1 when there are violations",
          report(bad, len(recs)) == 1)
    check("report() exits 0 on a clean range", report([], 3) == 0)

    # Fail-closed, both ways.
    try:
        load_predicate(os.path.join(HERE, "does-not-exist.py"))
        check("a missing predicate raises rather than passing", False)
    except Exception:
        check("a missing predicate raises rather than passing", True)
    try:
        git_log(["no-such-ref-xyz..HEAD"], HERE)
        check("an unresolvable range raises rather than reporting 0 commits", False)
    except Exception:
        check("an unresolvable range raises rather than reporting 0 commits", True)
    # --verify-vendor must be ABLE to fail. It shipped returning 0
    # unconditionally in a vendored copy (nothing beside it to compare to);
    # the embedded sha is what fixes that, so assert both directions.
    import shutil as _sh
    import tempfile as _tf
    d = _tf.mkdtemp(prefix="vendorcheck-")
    try:
        _sh.copyfile(os.path.abspath(__file__), os.path.join(d, "c.py"))
        _sh.copyfile(PREDICATE, os.path.join(d, "commit-identity-predicate.py"))
        r1 = subprocess.run([sys.executable, os.path.join(d, "c.py"),
                             "--verify-vendor"], stdout=subprocess.PIPE)
        check("--verify-vendor PASSES on an untouched vendored copy "
              "(no commit-msg beside it)", r1.returncode == 0,
              r1.stdout.decode())
        with open(os.path.join(d, "commit-identity-predicate.py"), "a") as fh:
            fh.write("\n# someone edited the vendored predicate\n")
        r2 = subprocess.run([sys.executable, os.path.join(d, "c.py"),
                             "--verify-vendor"], stdout=subprocess.PIPE)
        check("--verify-vendor FAILS when the vendored predicate is edited "
              "(it used to be unable to fail)", r2.returncode == 1,
              r2.stdout.decode())
    finally:
        _sh.rmtree(d, ignore_errors=True)

    saved = os.environ.get("GITHUB_EVENT_NAME")
    try:
        os.environ["GITHUB_EVENT_NAME"] = "schedule"
        ci_range()
        check("an unrecognised event raises rather than checking nothing", False)
    except Exception:
        check("an unrecognised event raises rather than checking nothing", True)
    finally:
        if saved is None:
            os.environ.pop("GITHUB_EVENT_NAME", None)
        else:
            os.environ["GITHUB_EVENT_NAME"] = saved

    print("SELF-TEST %s (%d failure(s))" % ("PASSED" if not fails else "FAILED",
                                            len(fails)))
    return 1 if fails else 0


def _sha(path):
    return hashlib.sha256(open(path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def verify_vendor():
    """The predicate must still be the reviewed commit-msg hook, byte for byte.

    Two checks, and the SECOND is the one that works in CI: comparing against
    the hook file only works beside the canonical copy, and a vendored copy has
    no hook next to it. The embedded sha is what lets the vendored copy fail.
    """
    if not PREDICATE_SHA256 or len(PREDICATE_SHA256) != 64:
        print("verify-vendor: PREDICATE_SHA256 is not stamped. This check "
              "cannot fail, so it must not pass. Run --stamp-vendor.")
        return 1
    if not os.path.isfile(PREDICATE):
        print("verify-vendor: no predicate at %s" % PREDICATE)
        return 1
    got = _sha(PREDICATE)
    if got != PREDICATE_SHA256:
        print("verify-vendor: MISMATCH -- the vendored predicate is not the "
              "reviewed commit-msg hook (%s, expected %s). Two texts of one "
              "rule is how a control stops being one; re-vendor from "
              "retro-vr-framework/experiments/fleet-hooks/identity/."
              % (got[:12], PREDICATE_SHA256[:12]))
        return 1
    if os.path.isfile(HOOK):
        if _sha(HOOK) != got:
            print("verify-vendor: MISMATCH -- commit-msg and the predicate "
                  "beside it have diverged. Re-copy, re-stamp, re-vendor.")
            return 1
        print("verify-vendor: predicate == commit-msg == stamp (%s). OK" % got[:12])
        return 0
    print("verify-vendor: predicate matches the stamped hook sha %s. OK "
          "(no commit-msg beside a vendored copy, by design)" % got[:12])
    return 0


def stamp_vendor():
    """Copy commit-msg -> the predicate and stamp its sha into this file."""
    if not os.path.isfile(HOOK):
        print("stamp-vendor: no commit-msg hook at %s -- run this beside the "
              "canonical copy" % HOOK)
        return 1
    data = open(HOOK, "rb").read()
    with open(PREDICATE, "wb") as fh:
        fh.write(data)
    os.chmod(PREDICATE, 0o755)
    want = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    me = os.path.abspath(__file__)
    src = open(me, "r", encoding="utf-8").read()
    import re as _re
    src = _re.sub(r'PREDICATE_SHA256 = "[0-9a-f]*"',
                  'PREDICATE_SHA256 = "%s"' % want, src, count=1)
    open(me, "w", encoding="utf-8").write(src)
    print("stamp-vendor: predicate re-copied and stamped %s" % want)
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--verify-vendor" in argv:
        return verify_vendor()
    if "--stamp-vendor" in argv:
        return stamp_vendor()
    repo = "."
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    try:
        mod = load_predicate()
        if "--range" in argv:
            rng = [argv[argv.index("--range") + 1]]
        elif "--ci" in argv:
            rng = ci_range(repo)
        else:
            rng = ["--all"]                  # a manual audit of all history
        text = git_log(rng, repo)
        recs = parse_log(text)
        bad = violations(recs, mod.decide)
    except Exception as exc:                 # FAIL CLOSED
        sys.stdout.write("commit-identity: CANNOT EVALUATE (%s).\n"
                         "A check that could not have failed is not a pass.\n"
                         % exc)
        return 2
    print("commit-identity: range %s" % " ".join(rng))
    return report(bad, len(recs))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
