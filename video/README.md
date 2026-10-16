# video/

Tools for normalizing a video library toward a clean, Plex-friendly layout —
movies as `Title (Year)/Title (Year).ext`, and TV/anime as
`Show (Year)/Season NN/Show - sNNeNN - Title.ext`.

| Tool | Purpose |
|---|---|
| `audit_movies.py` | Read-only report of naming/junk/duplicate/edition issues in a movie library |
| `normalize_movies.py` | Apply the movie normalization (dry-run by default), with logs + reversible undo |
| `audit_episodes.py` | Read-only structural + episode-naming report for a TV/anime library |
| `normalize_episodes.py` | Build/apply a Plex TV/anime layout; flags ambiguous cases |
| `map_absolute_episodes.py` | Resolve an absolute-numbered (anime) show via TheTVDB into season/episode |

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

## normalize_episodes.py
Builds a plan to lay out a TV/anime library as `Show (Year)/Season NN/Show - sNNeNN - Title.ext`.
For each show it cleans the folder name, parses each episode's season/episode number, and
classifies the show as **mappable** (safe to rename), or flags it as **absolute-numbered**
(needs a metadata lookup — never guessed), **mixed/unparsed**, or a **miscategorized movie**.
Shows split across multiple folders are reported as **merge candidates**.

```
python3.11 normalize_episodes.py DIR [--out preview.txt]
```

`--apply` reorganizes only the mappable, non-merge shows (creating `Season NN/` folders, renaming
episodes, leaving unparsed files in place), with a log and a reversible undo script rewritten after
every move. Merges and flagged shows stay manual. Log/undo filenames are namespaced by source
folder so normalizing two libraries on the same day can't clobber each other's undo.

## map_absolute_episodes.py
Handles the shows `normalize_episodes.py` flags as **absolute-numbered** (common for anime fansub
rips like `[Group] Show - 07` or `Show ep 07`). It reads each file's absolute episode number, looks
the series up on **TheTVDB**, and maps absolute → season/episode, producing authoritative
`Show (Year)/Season NN/Show - sNNeNN - Title.ext` names (titles come from TheTVDB).

```
python3.11 map_absolute_episodes.py SHOW_DIR [--name NAME] [--tvdb-id ID] \
                                    [--offline] [--apply] [--log-dir DIR]
```

- `--offline` — no network; just shows the absolute number parsed from each filename, so you can
  sanity-check parsing before spending an API call.
- Series match uses the cleaned folder name and prefers the TheTVDB result whose year matches the
  folder; use `--name`/`--tvdb-id` to override, and read the preview before `--apply`.

Requires `FIELDKIT_TVDB_API_KEY` in `.env` (see `example.env`); get a v4 API key at
https://thetvdb.com/dashboard. `--apply` is logged and reversible like the other tools.
