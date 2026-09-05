#!/usr/bin/env python3
"""INSTALLED FLEET-WIDE 2026-09-04 -- the fleet commit-identity guard.

Installed by the Architect's order ("install the identity hook fleet-wide")
into ``~/.git-templates/hooks/commit-msg`` and into the ``hooks/`` dir of all
38 git repos under ``/mnt/c/GitHub`` (via ``git rev-parse --git-common-dir``,
so worktrees share the parent's copy rather than getting an inert one).
``init.templatedir`` was already set to ``~/.git-templates``, so new clones and
``git init`` inherit it. No repo had a pre-existing ``commit-msg`` hook, so
nothing was overwritten.

Verified live after installing, in a throwaway repo, not from the self-test:
  committer "Claude Code"                    -> BLOCKED (names both surfaces)
  correct identity + Co-Authored-By trailer  -> BLOCKED
  correct identity, clean message            -> allowed, logs Patrick Carey/Patrick Carey
  --author alone, committer left as Claude   -> BLOCKED  (the documented trap)

Known limit, unchanged: ``--no-verify`` bypasses it, and 11 of the 15 measured
violations were committed off this machine (see doc 33 section on the cloud
runner), which no local hook reaches.

Enforces the two rules in ``~/.claude/CLAUDE.md`` that were measured at 15
violations across 4 repos (two further hits in pcsx2-VR are inherited upstream PCSX2 commits, excluded) (see ``docs/33-fleet-hooks-identity-artifacts.md``):

  1. no ``Co-Authored-By: Claude`` / ``Claude-Session:`` / ``Generated with
     [Claude Code]`` trailer in the commit message;
  2. neither the AUTHOR nor the COMMITTER is "Claude ..." or ``@anthropic.com``.

Why ``commit-msg`` and not ``pre-commit``, ``prepare-commit-msg`` or a
PreToolUse hook -- each claim below was PROBED on this box on 2026-09-04 in a
throwaway repo, not assumed:

* ``commit-msg`` is the ONLY hook that sees **both** surfaces at once. It gets
  the final message as ``argv[1]`` and both final identities from
  ``git var GIT_AUTHOR_IDENT`` / ``GIT_COMMITTER_IDENT``.
* Those two ``git var`` calls resolve the *effective* identity, so the hook sees
  through every way of setting it. Probe, config ``user.name = "Claude Code"``:

      bare commit           -> A=Claude Code    C=Claude Code     (both caught)
      --author only         -> A=Patrick Carey  C=Claude Code     (committer caught)
      GIT_COMMITTER_* + --author -> A=Patrick    C=Patrick        (passes)

  The middle line is the exact trap ``~/.claude/CLAUDE.md`` warns about --
  ``--author`` alone is not enough -- and this hook is the thing that detects
  it. ``pre-commit`` also sees both idents but never sees the message.
* Probed to FIRE on: ``-m``, a ``$(cat <<EOM ...)`` heredoc in ``-m``, ``-F
  file``, ``--amend``, a non-fast-forward ``merge``, and the editor path.
* Probed NOT to fire on: ``--no-verify``. That is the same known limit the
  fleet's ``pre-push`` guard already documents, and it is why the companion
  ``pretooluse-git-identity.py`` exists: a Claude-side hook can see
  ``--no-verify`` in the command string before git ever runs.
* **It protects every client, not just Claude Code** -- a terminal commit, an
  IDE commit, another agent, ``git rebase --exec``. That is the decisive
  advantage over a PreToolUse-only design, and it is why this is the primary
  recommendation and the Claude hook is defence in depth.

**Fails open.** Any exception, any unreadable message file, any ``git var``
failure -> exit 0 with a warning on stderr. A wrong attribution is a bad day; a
hook that wedges every commit in 38 repos is a worse one. The guard's teeth come
from the two checks it *can* evaluate, not from crashing when it cannot.

**Comment lines are stripped before matching** (``core.commentChar``, and
everything after a ``--- >8 ---`` scissors line), because the editor path was
probed to hand the hook the whole template including ``# ...`` help text.

Install (the Architect's call, per repo -- see the doc for the loop)::

    cp commit-msg <repo>/.git/hooks/commit-msg && chmod +x <repo>/.git/hooks/commit-msg
    cp commit-msg ~/.git-templates/hooks/commit-msg   # for repos cloned later

Do NOT install this by setting ``core.hooksPath`` globally: that redirects ALL
repos to one directory and would silently disable the 36 per-repo ``pre-push``
push guards this fleet already relies on. Verified: ``git config --global
core.hooksPath`` is currently unset, and ``init.templateDir`` is
``/home/pacarey/.git-templates``.

Self-test::

    python3 commit-msg --self-test
"""

import os
import re
import subprocess
import sys

# --- what is forbidden -------------------------------------------------------
# Anchored at line start, in git's own trailer form. A commit whose PROSE
# mentions the rule ("dropped the Co-Authored-By trailer") must still commit --
# that is a correct commit, and blocking it would be exactly the false positive
# this guard cannot afford. Only a real trailer line matches.
TRAILER_PATTERNS = (
    (re.compile(r"^\s*Co-authored-by\s*:.*\bclaude\b", re.I),
     "Co-Authored-By: Claude ... trailer"),
    (re.compile(r"^\s*Co-authored-by\s*:.*@anthropic\.com", re.I),
     "Co-Authored-By: ... @anthropic.com trailer"),
    (re.compile(r"^\s*Claude-Session\s*:", re.I),
     "Claude-Session: trailer"),
    (re.compile(r"^\s*(?:.{0,4}\s*)?Generated with \[Claude Code\]", re.I),
     "'Generated with [Claude Code]' line"),
    (re.compile(r"^\s*https://claude\.ai/code/session_", re.I),
     "claude.ai session URL line"),
)

#: An identity is forbidden if the display name begins with "claude" or the
#: address is an anthropic.com one. Deliberately narrow: it must not fire on
#: the Architect, and the fleet census found only these two shapes --
#: ``Claude Code <patrickfcarey@gmail.com>`` and ``Claude <noreply@anthropic.com>``.
BAD_NAME = re.compile(r"^\s*claude\b", re.I)
BAD_EMAIL = re.compile(r"@anthropic\.com\s*$", re.I)

IDENT = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^>]*)>")


def strip_comments(text, comment_char="#"):
    """Git's own message cleanup, applied before matching.

    Probed 2026-09-04: on the editor path the hook receives the entire template,
    including the ``# Please enter the commit message`` help block and, under
    ``commit.cleanup=scissors``, the whole diff. Matching that raw would fire on
    a scissors-mode diff that merely *contains* the trailer text.
    """
    out = []
    for line in (text or "").splitlines():
        if re.match(r"^\s*%s\s*-+\s*>8\s*-+" % re.escape(comment_char), line):
            break                      # scissors: nothing after this is the message
        if comment_char and line.startswith(comment_char):
            continue
        out.append(line)
    return "\n".join(out)


def check_message(text, comment_char="#"):
    """Return a list of human-readable violations found in the message."""
    body = strip_comments(text, comment_char)
    found = []
    for line in body.splitlines():
        for rx, label in TRAILER_PATTERNS:
            if rx.search(line) and label not in found:
                found.append(label)
    return found


def check_ident(role, ident):
    """``role`` is 'author'/'committer'; ``ident`` is a ``git var`` string.

    Returns a violation string or None. An unparseable ident returns None --
    fail open, per the module docstring.
    """
    if not ident:
        return None
    m = IDENT.match(ident)
    if not m:
        return None
    name, email = m.group("name"), m.group("email")
    if BAD_NAME.match(name) or BAD_EMAIL.search(email):
        return "%s is %s <%s>" % (role, name, email)
    return None


def decide(message, author_ident, committer_ident, comment_char="#"):
    """Pure. Returns (ok, [reasons]). Everything testable lives here."""
    reasons = []
    for label in check_message(message, comment_char):
        reasons.append("commit message carries a forbidden %s" % label)
    for role, ident in (("author", author_ident), ("committer", committer_ident)):
        v = check_ident(role, ident)
        if v:
            reasons.append(v)
    return (not reasons), reasons


def suggested_identity():
    """The name/email to put in the fix-it line, taken from live config."""
    name = git_out(["config", "--global", "--get", "user.name"]) or ""
    email = git_out(["config", "--global", "--get", "user.email"]) or ""
    if not name or BAD_NAME.match(name):
        name = "Patrick Carey"          # ~/.claude/CLAUDE.md, "Likely real name"
    if not email or BAD_EMAIL.search(email):
        email = "patrickfcarey@gmail.com"
    return name, email


def git_out(args):
    try:
        p = subprocess.run(["git"] + args, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=10)
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def report(reasons):
    name, email = suggested_identity()
    w = sys.stderr.write
    w("\n")
    w("  COMMIT REFUSED -- fleet identity rule (~/.claude/CLAUDE.md)\n")
    for r in reasons:
        w("    * %s\n" % r)
    w("\n")
    w("  Never attribute a commit to Claude, on either surface: no trailer,\n")
    w("  and neither the AUTHOR nor the COMMITTER may be Claude. --author\n")
    w("  alone is NOT enough; the committer comes from config or the env.\n")
    w("\n")
    w("  Re-run in this exact form, with the trailer removed:\n")
    w("\n")
    w('    GIT_COMMITTER_NAME="%s" \\\n' % name)
    w('    GIT_COMMITTER_EMAIL="%s" \\\n' % email)
    w('    git commit --author="%s <%s>" -m "..."\n' % (name, email))
    w("\n")
    w("  Do not reach for --no-verify. That bypasses this guard and puts the\n")
    w("  bad attribution on GitHub, which is the whole thing being prevented.\n")
    w("\n")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    try:
        path = argv[0]
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            message = fh.read()
    except Exception as exc:                                  # fail open
        sys.stderr.write("commit-msg guard: cannot read message (%s); "
                         "allowing.\n" % exc)
        return 0
    try:
        comment_char = git_out(["config", "--get", "core.commentChar"]) or "#"
        if comment_char == "auto":
            comment_char = "#"
        ok, reasons = decide(message,
                             git_out(["var", "GIT_AUTHOR_IDENT"]),
                             git_out(["var", "GIT_COMMITTER_IDENT"]),
                             comment_char)
    except Exception as exc:                                  # fail open
        sys.stderr.write("commit-msg guard: internal error (%s); allowing.\n" % exc)
        return 0
    if ok:
        return 0
    report(reasons)
    return 1


# --- self-test ---------------------------------------------------------------

CASES = [
    # (name, message, author_ident, committer_ident, expect_ok)
    ("clean commit, both identities correct",
     "docs: point agents at the fleet tools index",
     "Patrick Carey <patrickfcarey@gmail.com> 1788 -0500",
     "Patrick Carey <patrickfcarey@gmail.com> 1788 -0500", True),

    ("the trailer this session's system prompt tells the model to append",
     "feat: whatever\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
     "Claude-Session: https://claude.ai/code/session_01BdTw",
     "Patrick Carey <patrickfcarey@gmail.com> 1788 -0500",
     "Patrick Carey <patrickfcarey@gmail.com> 1788 -0500", False),

    ("older trailer form (Claude Fable 5.1) -- the loadout-pipeline-profiles shape",
     "x\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>",
     "Patrick Carey <patrickfcarey@gmail.com> 1 -0",
     "Patrick Carey <patrickfcarey@gmail.com> 1 -0", False),

    ("lowercase / spaced trailer key still caught",
     "x\n\nco-authored-by :  Claude <noreply@anthropic.com>",
     "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", False),

    ("PR-body markers pasted into a commit body",
     "x\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)\n"
     "\nhttps://claude.ai/code/session_01BdTw",
     "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", False),

    ("MUST NOT FIRE: prose that discusses the rule",
     "chore: strip the Co-Authored-By: Claude trailer from the release script\n"
     "\nThe hook now refuses any commit whose body carries Claude-Session:.",
     "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", True),

    ("MUST NOT FIRE: the trailer only inside a stripped comment line",
     "real subject\n# Co-Authored-By: Claude <noreply@anthropic.com>\n",
     "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", True),

    ("MUST NOT FIRE: scissors-mode diff below the cut quoting the trailer",
     "real subject\n# ------------------------ >8 ------------------------\n"
     "+Co-Authored-By: Claude <noreply@anthropic.com>\n",
     "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", True),

    ("blitz-command shape: both identities 'Claude Code', real email",
     "summary",
     "Claude Code <patrickfcarey@gmail.com> 1 -0",
     "Claude Code <patrickfcarey@gmail.com> 1 -0", False),

    ("loadout-pipeline-profiles shape: both identities 'Claude', anthropic email",
     "rg-arc-d: add TODO-verify-paths.md",
     "Claude <noreply@anthropic.com> 1 -0",
     "Claude <noreply@anthropic.com> 1 -0", False),

    ("THE DOCUMENTED TRAP: --author set, committer still Claude Code",
     "a good message",
     "Patrick Carey <patrickfcarey@gmail.com> 1 -0",
     "Claude Code <patrickfcarey@gmail.com> 1 -0", False),

    ("mirror of the trap: committer fixed, author still Claude",
     "a good message",
     "Claude Code <patrickfcarey@gmail.com> 1 -0",
     "Patrick Carey <patrickfcarey@gmail.com> 1 -0", False),

    ("anthropic.com address under a human-looking name",
     "a good message",
     "P. Carey <noreply@anthropic.com> 1 -0",
     "P. Carey <noreply@anthropic.com> 1 -0", False),

    ("MUST NOT FIRE: a surname merely containing 'claude'",
     "upstream cherry-pick",
     "Jean Claudel <jc@example.org> 1 -0",
     "Patrick Carey <p@x> 1 -0", True),

    ("FAIL OPEN: unparseable ident strings are allowed, not blocked",
     "a good message", "", "", True),

    ("FAIL OPEN: garbage ident is allowed, not blocked",
     "a good message", "?????", "?????", True),

    ("MUST NOT FIRE: empty message (git rejects it later, not us)",
     "", "Patrick Carey <p@x> 1 -0", "Patrick Carey <p@x> 1 -0", True),

    ("both surfaces at once -> both reasons reported",
     "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
     "Claude Code <p@x> 1 -0", "Claude Code <p@x> 1 -0", False),
]


def self_test():
    ok_all = True
    for name, msg, a, c, expect in CASES:
        got, reasons = decide(msg, a, c)
        good = (got == expect)
        ok_all = ok_all and good
        print("%s  %s" % ("PASS" if good else "FAIL", name))
        if not good or reasons:
            for r in reasons:
                print("        -> %s" % r)
    # The last case violates BOTH surfaces at once. A guard that reported only
    # the message and stayed silent about the identity would send the agent
    # round a second time, so assert that both surfaces are named.
    _, reasons = decide(CASES[-1][1], CASES[-1][2], CASES[-1][3])
    joined = " ".join(reasons)
    multi = ("commit message carries" in joined
             and "author is" in joined and "committer is" in joined)
    ok_all = ok_all and multi
    print("%s  last case names message + author + committer (%d findings)"
          % ("PASS" if multi else "FAIL", len(reasons)))
    print("SELF-TEST %s (%d cases)" % ("PASSED" if ok_all else "FAILED", len(CASES) + 1))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
