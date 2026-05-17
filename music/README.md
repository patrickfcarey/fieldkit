# music/

Tools for auditing and repairing the metadata of an audio library --
checking tags, filling gaps, and embedding album cover art.

| Tool | Purpose |
|---|---|
| `audit_tags.py` | Read-only report of missing/inconsistent tags and missing cover art |
| `tag_music.py` | Conservatively fill blank tags and embed cover art |

## audit_tags.py

Read-only. Scans one or more directories and reports, per directory and
overall: files missing core tags, files with no embedded cover art,
files whose tags disagree with their filename, and the distinct album
count. It modifies nothing.

```
python3.11 audit_tags.py DIR [DIR ...]
```

## tag_music.py

Fills *only* what is missing -- blank genre, date, and track tags -- and
embeds cover art where none is present. It never overwrites a tag that
already holds a value.

Albums are grouped by folder + album tag. Per album it looks up:

- **MusicBrainz** -- release year and the release-group id.
- **Cover Art Archive** -- the front cover, keyed by release-group id.
- **Discogs** -- genre (from the moderated "style" field), and a
  fallback cover image when the Cover Art Archive has none.

The release year prefers a year found in the folder name -- this is
edition-aware, so `[2004 Remastered]` yields 2004 -- and falls back to
MusicBrainz. An album with no clear majority artist is treated as
various-artists and looked up by album title alone.

```
# preview the planned changes, write nothing
python3.11 tag_music.py DIR [DIR ...] --dry-run

# tag for real
python3.11 tag_music.py DIR [DIR ...]

# limit to albums whose title matches
python3.11 tag_music.py DIR --album "Rust in Peace"
```

Each changed file is remuxed losslessly (`ffmpeg -c copy`) to a temp
file, verified, then atomically swapped in. Existing audio is never
re-encoded.

## Dependencies

- `python` >= 3.11 (standard library only)
- `ffmpeg`, `ffprobe`
- Network access to `musicbrainz.org`, `coverartarchive.org`,
  `api.discogs.com`

## Configuration

Optional, via the repo-root `.env` file (see `example.env`):

- `FIELDKIT_DISCOGS_TOKEN` -- a free Discogs personal access token
  (discogs.com/settings/developers). Genre lookups work without it, but
  the **Discogs cover-art fallback requires it** -- the Discogs search
  API omits image URLs for unauthenticated requests. A caller-supplied
  environment variable of the same name overrides the `.env` value.

## Known limitations

- **The Discogs cover fallback is unverified** -- it is wired but has
  not yet been exercised against a real token.
- **FLAC art embedding** -- a small number of FLAC files have failed the
  post-embed verification ("cover art missing from remuxed file"); not
  yet root-caused. mp3 art embedding is solid.
- **Various-artists albums** are looked up by album title alone, with no
  artist constraint -- less precise, and it can occasionally match the
  wrong release.
- Genre reflects Discogs' "style" data as-is, which is uneven across a
  catalog.

## Exit codes

`tag_music.py`: `0` success, `1` bad input or usage, `2` a required tool
is missing or a step failed. `audit_tags.py` is a report and always
exits `0`.
