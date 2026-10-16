# Handoff

Where fieldkit stands and what to do next. **Rewritten, not appended**: the running history is in
[`worker_log.md`](worker_log.md). Read `AGENTS.md` first.

---

## RESUME HERE (2026-10-16)

**`main` holds everything.** On the owner's word, `dev` (the `music/`, `video/` and `optical/`
tools, 12 commits from 2026-05-17 to 2026-06-01) was merged into `main` by a merge commit on branch
`dm4800/merge-dev`, then `main` was fast-forwarded to it and pushed to `origin` and the private
mirror.

Before the merge, `dev`'s commits were rebuilt as `dm4800/dev-clean` (owner's choice): Patrick Carey
as author and committer, the three Claude co-author trailers removed, messages and author dates
kept, tree byte-identical to `origin/dev`.

Waiting on the owner:
- **`origin/dev` still holds the old commits** (trailers and the machine identity). Its content is
  all in `main` now. Deleting it, or leaving it as a record, is the owner's call:
  `git push origin --delete dev`
- The branches `dm4800/fix-tables`, `dm4800/dev-clean` and `dm4800/merge-dev` are merged and can be
  deleted.

## State (OBSERVED 2026-10-16)

- **Tools on `main`:**
  - `git/git-exposure-census.py`: `--self-test` 18/18 when last run (2026-09-21).
  - `markdown/fix_tables.py`: `--self-test` 11/11; unit tests 5/5.
  - `music/`, `video/`, `optical/`: unit tests `optical/tests` 16/16 and `music/tests` 14/14 under
    Python 3.11 at the merge. `music/tests/run_target_test.py` runs against a real library and was
    not run.
- **Merge conflicts resolved:** `.gitignore` takes `dev`'s (a superset of `main`'s one line);
  `example.env` takes `dev`'s template plus a `git/` section with `GIT_CENSUS_ROOTS`.
- **Remotes:** `origin` is the GitHub repo. `upstream` is the same repo with its push URL blocked,
  so the hand-off tool has an `upstream/main` to count against. `nas` is the private mirror.
- **Working tree noise:** on a Windows-mounted checkout, `LICENSE` and `README.md` show modified.
  Every change in them is a CRLF flip; `git diff --ignore-cr-at-eol` shows none. HEAD stores LF.
  Write new files with LF, and stage named files only.

## Machines and paths

- Commit identity: Patrick Carey `<patrickfcarey@gmail.com>` as author AND committer, no attribution
  lines (`AGENTS.md` rule 1).
- Machine-specific values go in `.env`, never in a tracked file (`example.env` is the template).

## Do not

- Do not merge or push `main` without the owner's word. Work branches may be pushed to `origin`
  (the owner's rule since 2026-09-27).
- Do not put a LAN address, host name, machine path, private product or repository name, or
  credential in any tracked file, this one included.
- Do not use porcelain `git diff` or plain `git status` in a tool that audits other checkouts. Both
  take `index.lock`; see the census's `git_raw` and the 2026-09-21 worker-log entry.
- Do not add a sibling of an existing script (`AGENTS.md` rule 4).

## Still owed

- The census counts remote-tracking refs only. A branch a mirror holds under `refs/hosts/<prefix>/`
  or `refs/wip/` reads as "on no remote". Reading the mirror's other namespaces would close that.
  It needs a network call per remote, so it would be an opt-in flag.
- A submodule whose `.git` file names a Windows absolute path makes `git status` fail under WSL. The
  census reports that checkout as UNREAD, which is correct. Its message cannot say which submodule.
- `fix_tables.py` leaves blockquoted tables (`> | a |`) alone; see its docs for the other limits.
- `fix_tables.py` targets Python 3.9+, below the README's 3.11 baseline that arrived with `dev`;
  that is allowed (it relies on nothing newer than its stated minimum).
