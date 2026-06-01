# video/

Tools for normalizing a video library toward a clean, Plex-friendly layout —
movies as `Title (Year)/Title (Year).ext`, and TV/anime as
`Show (Year)/Season NN/Show - sNNeNN - Title.ext`.

| Tool | Purpose |
|---|---|
| `audit_movies.py` | Read-only report of naming/junk/duplicate/edition issues in a movie library |
| `normalize_movies.py` | Apply the movie normalization (dry-run by default), with logs + reversible undo |
| `audit_episodes.py` | Read-only structural + episode-naming report for a TV/anime library |

All tools are read the directory directly, use the standard library only, and (for the
apply tool) move/rename **within one filesystem**, so changes are atomic renames — no copies.

## Working rule
**preview → sign-off → apply → quarantine (never hard-delete).**
`audit_*` and the default dry-run of `normalize_movies.py` change nothing. Applying writes a
log and a reversible `undo-*.sh`, and `dedupe` moves superseded copies to a dated
`_duplicates-DATE/` quarantine folder rather than deleting them.

## audit_movies.py
Read-only. Scans a movie directory and reports: folders carrying release junk, loose video
files not in their own folder, duplicate/collision groups (with sizes), edition/cut variants,
junk/incomplete files, and entries with no parseable year.

```
python3.11 audit_movies.py DIR [--out report.txt]
```

A trailing `{edition-...}` tag is treated as part of a film's identity — a film and its
edition are **not** reported as duplicates of each other.

## normalize_movies.py
Applies the normalization in four independent steps. **Dry-run by default**; add `--apply`.

```
python3.11 normalize_movies.py DIR [--step {strip-tags,fold-loose,dedupe,editions,all}] \
                                   [--apply] [--log-dir DIR] [--protect "Title (Year)"]
```

- `strip-tags` — drop release junk from folder names → `Title (Year)`. Defers anything that
  belongs to a duplicate group or carries an edition keyword.
- `fold-loose` — move loose `Title (Year).ext` files into `Title (Year)/Title (Year).ext`.
- `dedupe` — resolve duplicate groups **keep-largest**; quarantine the smaller copies. Compares
  real sizes — the larger copy is often a loose remux, not the folder. Deletes nothing.
- `editions` — reformat edition/cut folders → `Title (Year) {edition-...}`. Skips names where
  the keyword is the real title (extend with `--protect`).

Logs and the quarantine folder default to the **parent** of `DIR` (override with `--log-dir`).

## audit_episodes.py
Read-only. For each show under one or more roots, reports video count, whether it uses season
subfolders or is flat, and the episode-naming scheme it uses (`SxxExx`, `NxNN`, `Season N`,
absolute number, fansub `[group]` prefix). Use it to scope a TV/anime cleanup before touching
anything.

```
python3.11 audit_episodes.py DIR [DIR ...]
```

## Planned
- `normalize_episodes.py` — restructure shows to `Show (Year)/Season NN/Show - sNNeNN - Title.ext`,
  merge shows split across multiple folders, and **flag** (not guess) ambiguous cases such as
  anime absolute-numbering that needs a metadata lookup to map to season/episode.
