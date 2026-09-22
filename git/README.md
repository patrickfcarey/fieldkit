# git/ — tools that look at git checkouts from the outside

| Tool | One line | Read-only? |
|---|---|---|
| `git-exposure-census.py` | How much work on THIS machine exists nowhere else: per checkout (worktrees included), commits on no remote, repos with no pushable remote, real dirty edits vs line-ending noise, untracked files, stashes, branches without upstream. TSV/JSON out; exit 1 as a gate; `--self-test`. | yes |

Roots come from the CLI, else `.env` (`GIT_CENSUS_ROOTS`, colon-separated), else the
current directory. No machine names, hosts or paths are baked in — this repo is public.

```
python3 git/git-exposure-census.py /path/to/repos ~/worktrees --out census.tsv
python3 git/git-exposure-census.py --self-test
```

Checkouts are read in parallel (`--jobs`, default 8), and linked worktrees are followed
wherever they live. The slow part on a Windows-mounted (`/mnt/c`) checkout is the
working-tree walk of `git status`, which can take many minutes on a large tree. A
checkout whose status fails, or takes longer than `--timeout` seconds (default 300), is
reported **UNREAD** and fails the gate: "could not look" is never reported as "clean".

It never writes to a checkout: every git call runs with `--no-optional-locks`, and real
edits come from plumbing (`diff-files`, `diff-index --cached`), because porcelain
`git diff` rewrites the index even under that flag. So a run killed halfway cannot leave
an `index.lock` behind. Line-ending flips and mode-only changes (a 755/644 flip) count as
noise, not edits.

It counts remote-tracking refs only. A branch a mirror holds under another namespace
(`refs/hosts/<prefix>/`, `refs/wip/`) still reads as "on no remote"; look at the mirror
before calling it lost.
