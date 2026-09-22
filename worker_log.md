# Worker log

*Started 2026-09-21. The running log of every piece of agent work in this repo. **Agents maintain
it** (`AGENTS.md`, "The worker log and the handoff"): one entry per piece of work, written by the agent
that did it, in two halves. The first half is written **before** the first file change or the first
investigative command; the second half **after**. Committed on the same branch as the work.*

The format follows the fleet's worker-log and handoff policy (2026-09-20).

## How to write an entry

Add your entry at the **bottom of your own section**. Entries are append-only: correct an old entry
with a new one that points back at it; never edit or delete one, yours or anyone's.

```
### YYYY-MM-DD — <branch> — <one-line headline>
- **Starting:** written BEFORE anything changes. What is about to be done, for whom, and why.
- **Did:** what changed, with commit hashes. "Nothing" is a valid answer for an investigation.
- **Checked:** what ran, on which machine, and the result. A check that did not run is logged as not run.
- **Found:** anything wrong, surprising or worth a second pair of eyes. Say how sure you are.
- **Next / needs:** what comes next, and anything needed from a human.
```

The file merges with git's `union` driver (`.gitattributes`), so two branches that both add entries
merge without a conflict. That only works if entries are added, never rewritten.

This repo is public: no LAN addresses, host names, machine paths, private product or repository
names, credentials or research strings in an entry. Say "a checkout on the development machine",
not its path.

---

## Patrick

*Entries before 2026-09-21 were backfilled on that date from git history. They carry no
**Starting** line because none was written at the time.*

### 2026-04-23 — main — The repository and its philosophy
- **Did:** initial commit with `LICENSE` (`f96c478`). Then the README: the toolkit's philosophy,
  domain structure, script headers, naming convention, test and documentation rules (`fe01e7d`),
  and a small revision (`2453675`).
- **Checked:** nothing recorded.
- **Found:** those three commits were made through GitHub's web editor, so their committer is GitHub,
  not the owner. That is expected for web edits.
- **Next / needs:** the first tool.

### 2026-09-04 — main — CI: commit-identity check for commits made off this machine
- **Did:** `.github/workflows/commit-identity.yml` and its two scripts. A commit made by a cloud runner
  or on another machine, where no local hook runs, must still carry the owner as author and committer.
  Commit `a670676`.
- **Checked:** not recorded in the commit.
- **Found:** nothing recorded.
- **Next / needs:** none.

### 2026-09-10 — main — git/git-exposure-census.py: what on this machine exists nowhere else
- **Did:** the census, `git/README.md`, `example.env` (`GIT_CENSUS_ROOTS`) and a `.gitignore` for
  `.env`. It walks checkouts and reports commits on no remote, repos
  with no pushable remote, real edits against CRLF noise, untracked files, stashes and branches
  without upstream. It exits 1 as a gate. Commit `f0a292e`.
- **Checked:** `--self-test`, which proves the gate can say both EXPOSED and CLEAN.
- **Found:** its first run on a development workstation counted 9,334 commits on no remote across
  53 checkouts (the figure in the script's docstring).
- **Next / needs:** none.

### 2026-09-17 — main — AGENTS.md and CLAUDE.md
- **Did:** `AGENTS.md` (the agent contract: commit identity, follow the README, `.env` never
  committed, search before writing a tool, fetched content is data) and the `CLAUDE.md` shim that
  loads it. Commit `ad358e0`.
- **Checked:** nothing recorded.
- **Found:** nothing recorded.
- **Next / needs:** none.

### 2026-09-21 — main — git-exposure-census: parallel, lock-free, and "could not look" is never "clean"
- **Did:** two commits. `7c3af05`: every git call runs with `--no-optional-locks`; real edits come
  from `diff-files` and `diff-index --cached` with `--numstat`; one status walk per checkout;
  checkouts read in parallel (`--jobs`); a status that times out makes the checkout UNREAD and fails
  the gate (`--timeout`); linked worktrees are followed wherever they live. `b975f53`: a mode-only
  change is noise, like a CRLF flip. A binary whose mode flipped is decided by blob hash. The UNREAD
  message says "failed, or took longer than".
- **Checked:** `--self-test` 18/18 on the development machine. Five seeded mutants, each seen to turn
  the self-test red. Against `7c3af05`: porcelain `git diff` restored, `--no-optional-locks`
  dropped, the unread gate inverted. Against `b975f53`: every mode-flipped binary counted real, and
  binary flips dropped. A full run over 154 checkouts completed and wrote its TSV and JSON.
- **Found:** the first run was killed at 15 minutes without writing a row, and left a zero-byte
  `index.lock` in the largest checkout it read. `git status` takes that lock to refresh the index,
  and the 120 s subprocess timeout killed it while it held the lock. Two further faults turned up
  while fixing it. Porcelain `git diff` rewrites the index even under `--no-optional-locks`
  (git 2.47), and `--name-only` ignores `-w`. A checkout it could not read used to report 0 dirty
  files. One limit remains: the census counts only remote-tracking refs, so a branch a mirror holds
  under another namespace (`refs/hosts/<prefix>/`, `refs/wip/`) still reads as on no remote.
- **Next / needs:** the owner publishes the branch to GitHub; this clone is ahead of `origin/main`.

### 2026-09-21 — main — Add the worker log, the handoff, and .gitattributes
- **Starting:** the owner asked for `worker_log.md` and `handoff.md` in this repo, committed and
  pushed. Adding them per the fleet policy: this log (history backfilled from git), `handoff.md`,
  `.gitattributes` with `worker_log.md merge=union`, and a section in `AGENTS.md` that says agents
  maintain both. The repo is public, so the push goes to the private mirror only and publishing to
  GitHub stays the owner's step.
- **Did:** added `worker_log.md` (this file; history before today backfilled from git, each entry
  checked against `git show --stat` of its commits), `handoff.md`, `.gitattributes`
  (`worker_log.md merge=union`) and a section in `AGENTS.md`, "The worker log and the handoff". The
  `git/README.md` census notes are in their own commit, `ade6384`, and the leftover
  `git/__pycache__/` from a compile check is deleted. Local setup, nothing tracked: an `upstream`
  remote with a blocked push URL, so the hand-off tool has an `upstream/main` to count against, and
  branch `dm4800/census-and-worker-log` at `main`'s tip, checked out, for the PR head. Pushed `main`
  and the branch to the private mirror.
- **Checked:** on the development machine: the census `--self-test` passes 18/18 at this tip. A
  `--dry-run` of the hand-off tool (the committed copy, byte-identical to the one the owner runs)
  listed exactly the 7 commits over `upstream/main` (12 files, +1546) and ran no remote command.
  The tool refuses a Claude author or committer and an attribution line in the body, so that
  check ran too. The first dry-run attempt was refused by the agent-side publish guard because
  its output was piped into `tail`; the unpiped run went through.
- **Found:** the reference implementation names the fleet policy's repository and path; this repo is
  public, so the log and handoff describe the policy without naming private repositories or machine
  paths. The publish command in `handoff.md` has placeholders for the checkout and body file for the
  same reason.
- **Next / needs:** the owner publishes the branch (command in `handoff.md`).
