# Handoff

Where fieldkit stands and what to do next. **Rewritten, not appended**: the running history is in
[`worker_log.md`](worker_log.md). Read `AGENTS.md` first.

---

## RESUME HERE (2026-09-21)

**Seven commits are waiting on the owner to publish.** They sit on branch
`dm4800/census-and-worker-log`, which equals local `main`, seven commits over `upstream/main`
(`2453675`). This repo is public, so the agent pushed them to the private mirror only. Publishing
to GitHub is the owner's step, through the fleet's PR hand-off tool (`open_pr.sh`, run from the
owner's own terminal, `--dry-run` first):

```
open_pr.sh --repo <this checkout> --upstream patrickfcarey/fieldkit \
  --branch dm4800/census-and-worker-log --expect-commits 7 --base main --remote origin \
  --title "git-exposure-census: parallel and lock-free; the worker log and the handoff" \
  --body-file <the PR body prepared beside it>
```

The seven commits:
1. `a670676` CI: commit-identity check for commits made off this machine
2. `f0a292e` `git/git-exposure-census.py`, first version
3. `ad358e0` `AGENTS.md` and `CLAUDE.md`
4. `7c3af05` census: parallel, lock-free, and "could not look" is never "clean"
5. `b975f53` census: a mode-only change is noise, like a CRLF flip
6. `ade6384` `git/README.md` brought up to date with 4 and 5
7. the commit that adds this file, `worker_log.md`, `.gitattributes` and the `AGENTS.md` section

A `--dry-run` of exactly this command passed on 2026-09-21: 7 commits, 12 files, +1546, no Claude
identity or attribution line. The checkout is on the branch, as the tool requires.

After the PR merges: `git switch main && git pull --ff-only upstream main`, then delete the branch.

## State (OBSERVED 2026-09-21)

- **One tool:** `git/git-exposure-census.py`. `--self-test` passes 18/18 on the development machine,
  and five seeded mutants each turn it red. A full run over 154 checkouts completed.
- **Remotes:** `origin` is the public GitHub repo. `upstream` is the same repo with its push URL
  blocked, so the hand-off tool has an `upstream/main` to count against. `nas` is the private mirror.
- **Working tree noise:** on a Windows-mounted checkout, `LICENSE` and `README.md` show modified.
  Every change in them is a CRLF flip; `git diff --ignore-cr-at-eol` shows none. HEAD stores LF.
  Write new files with LF, and stage named files only.

## Machines and paths

- Commit identity: Patrick Carey `<patrickfcarey@gmail.com>` as author AND committer, no attribution
  lines (`AGENTS.md` rule 1).
- Machine-specific values (census roots) go in `.env`, never in a tracked file (`example.env` is the
  template).

## Do not

- Do not push to `origin`. It is public, and publishing is the owner's.
- Do not put a LAN address, host name, machine path, private product or repository name, or
  credential in any tracked file, this one included.
- Do not use porcelain `git diff` or plain `git status` in a tool that audits other checkouts. Both
  take `index.lock`; see the census's `git_raw` and the 2026-09-21 worker-log entry.
- Do not add a sibling of an existing script (`AGENTS.md` rule 4).

## Still owed

- The owner publishes the branch above.
- The census counts remote-tracking refs only. A branch a mirror holds under `refs/hosts/<prefix>/`
  or `refs/wip/` reads as "on no remote". Reading the mirror's other namespaces would close that.
  It needs a network call per remote, so it would be an opt-in flag.
- A submodule whose `.git` file names a Windows absolute path makes `git status` fail under WSL. The
  census reports that checkout as UNREAD, which is correct. Its message cannot say which submodule.
