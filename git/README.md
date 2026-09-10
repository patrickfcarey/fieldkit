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

Slow on Windows-mounted (`/mnt/c`) checkouts with large histories: `git rev-list` over
a multi-GB `.git` on NTFS through WSL takes minutes per repo. Run it from a timer, not
interactively, or point it at one root at a time.
