# Handoff

Where fieldkit stands and what to do next. **Rewritten, not appended**: the running history is in
[`worker_log.md`](worker_log.md). Read `AGENTS.md` first.

---

## RESUME HERE (2026-10-16)

**Branch `dm4800/fix-tables`, one commit over `main` (`abcfe55`), pushed to `origin` and the
private mirror.** It adds `markdown/fix_tables.py`, the tool `README.md` has always used as its
example and that was never written, plus `markdown/README.md`, `markdown/docs/fix_tables.md` and
`markdown/tests/test_fix_tables.py`.

Waiting on the owner: merging the branch into `main` (the agent does not merge `main` unasked).

```
git switch main && git merge --ff-only dm4800/fix-tables && git push origin main
```

To check it first:

```
python3 markdown/fix_tables.py --self-test                 # 11 of 11
python3 -m unittest discover -s markdown/tests             # 5 tests, OK
```

## State (OBSERVED 2026-10-16)

- **Two tools:**
  - `git/git-exposure-census.py`: `--self-test` 18/18 when last run (2026-09-21).
  - `markdown/fix_tables.py`: `--self-test` 11/11. A copy with padding disabled fails 9 of 11.
    Run over a 1,685-line Markdown index (990 table rows), it changed no cell's text, and a second
    run changed nothing.
- **PR #1** (`dm4800/census-and-worker-log`, the census and the worker log) is merged into `main`.
- **Remotes:** `origin` is the GitHub repo. `upstream` is the same repo with its push URL blocked,
  so the hand-off tool has an `upstream/main` to count against. `nas` is the private mirror.
- **Working tree noise:** on a Windows-mounted checkout, `LICENSE` and `README.md` show modified.
  Every change in them is a CRLF flip; `git diff --ignore-cr-at-eol` shows none. HEAD stores LF.
  Write new files with LF, and stage named files only.

## Machines and paths

- Commit identity: Patrick Carey `<patrickfcarey@gmail.com>` as author AND committer, no attribution
  lines (`AGENTS.md` rule 1).
- Machine-specific values (census roots) go in `.env`, never in a tracked file (`example.env` is the
  template).

## Do not

- Do not merge or push `main` without the owner's word. Work branches may be pushed to `origin`
  (the owner's rule since 2026-09-27; it replaced the older "never push to origin" line here).
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
