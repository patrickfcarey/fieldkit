#!/usr/bin/env python3
# Name: tag_music.py
# Description: Conservatively fill missing audio tags and embed album
#              cover art across a music library. Only blank tags are
#              filled; existing tags are never overwritten.
# Usage: python3.11 tag_music.py DIR [DIR ...] [--album NAME] [--dry-run] [--limit N]
# Inputs: directories of audio files (mp3, flac, m4a)
# Outputs: tags written in place; a per-album report to stdout
#
# Environment:
#   Tested:
#     - Oracle Linux 9, Python 3.11, ffmpeg 7.x
#   Dependencies:
#     - python >= 3.11 (standard library only)
#     - ffmpeg, ffprobe
#     - network access to musicbrainz.org, coverartarchive.org,
#       api.discogs.com
#
# Data sources:
#   - Folder name   : release year, when the folder name carries one
#   - MusicBrainz   : release year fallback + release-group id
#   - Cover Art Arch: front cover image (keyed by release-group id)
#   - Discogs       : genre ("style" field) + fallback cover image
#
# Assumptions:
#   - Files are grouped into albums by folder + album tag; an album
#     with no majority artist is treated as various-artists
#   - title/artist/album tags are already correct (audit confirmed) and
#     are NOT touched
# Failure Modes:
#   - A lookup miss leaves that value unfilled; the file is reported
#   - ffmpeg output is verified before it replaces the original
# Notes:
#   - Conservative: fills only blank genre/date/track; embeds art only
#     where missing. Never overwrites a non-blank tag.
#   - Exit codes: 0 ok, 1 bad usage, 2 a required tool is missing.

"""Conservatively fill missing audio tags and embed album cover art."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

MIN_PYTHON = (3, 11)
AUDIO_EXTS = {".mp3", ".flac", ".m4a"}
USER_AGENT = "fieldkit-tagger/0.1 ( https://github.com/patrickfcarey )"

_last_hit: dict[str, float] = {}


def require_python(minimum=MIN_PYTHON):
    if sys.version_info < minimum:
        want = ".".join(str(n) for n in minimum)
        have = ".".join(str(n) for n in sys.version_info[:3])
        sys.exit("error: Python {0}+ required, this is {1}".format(want, have))


def _repo_root():
    """First ancestor of this file that contains .git or example.env."""
    here = Path(__file__).resolve()
    for directory in [here] + list(here.parents):
        if (directory / ".git").exists() or (directory / "example.env").is_file():
            return directory
    return None


def _dotenv_value(key):
    """Return `key` from the repository .env file, or '' if it is not set."""
    root = _repo_root()
    if root is None:
        return ""
    env_path = root / ".env"
    if not env_path.is_file():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        if name.strip() == key:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            return val
    return ""


# Discogs token (https://www.discogs.com/settings/developers). Optional:
# genre lookups work without it, but the Discogs cover-art fallback needs
# an authenticated request. A caller-supplied environment variable wins;
# otherwise the repository .env file is consulted.
DISCOGS_TOKEN = (os.environ.get("FIELDKIT_DISCOGS_TOKEN", "").strip()
                 or _dotenv_value("FIELDKIT_DISCOGS_TOKEN").strip())

# Minimum seconds between requests to each host (politeness / rate limits).
# Discogs allows 25 req/min unauthenticated (2.4 s/req) and 60 req/min with
# a token (1.0 s/req). Use the token limit when authenticated, conservative
# unauthenticated limit otherwise so we never trigger a 429.
THROTTLE = {
    "musicbrainz.org": 1.1,
    "api.discogs.com": 1.1 if DISCOGS_TOKEN else 2.5,
    "coverartarchive.org": 0.0,
}


def _throttle(host):
    wait = THROTTLE.get(host, 1.0)
    now = time.monotonic()
    elapsed = now - _last_hit.get(host, 0.0)
    if elapsed < wait:
        time.sleep(wait - elapsed)
    _last_hit[host] = time.monotonic()


def http_get(url):
    """GET a URL, returning raw bytes, or None on failure."""
    host = urllib.parse.urlparse(url).netloc
    _throttle(host)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as exc:  # network/HTTP errors are non-fatal per album
        print("  ! request failed ({0}): {1}".format(url, exc), file=sys.stderr)
        return None


def http_get_json(url):
    raw = http_get(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def ffprobe(path):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None


def format_tags(data):
    raw = data.get("format", {}).get("tags") or {}
    return {k.lower(): (v or "").strip() for k, v in raw.items()}


def has_cover_art(data):
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            if (stream.get("disposition") or {}).get("attached_pic"):
                return True
    return False


def track_from_filename(path):
    """Best-effort track number from the filename, or None."""
    stem = path.stem
    parts = stem.split(" - ")
    if len(parts) >= 4 and re.fullmatch(r"\d{1,3}", parts[2].strip()):
        return int(parts[2].strip())
    match = re.match(r"\s*(\d{1,3})[ .\-_]", stem)
    return int(match.group(1)) if match else None


def year_from_folder(path):
    """Extract a release year from the file's parent folder name, or None.

    Prefers a year inside [...] or (...) -- that is where these rips
    annotate the edition, e.g. "1990 - Rust In Peace [2004 Remastered]"
    yields 2004, not the 1990 sort prefix. Otherwise any 19xx/20xx year
    in the folder name is used.
    """
    folder = path.parent.name
    for segment in re.findall(r"[\[(]([^\[\]()]*)[\])]", folder):
        match = re.search(r"\b(19\d\d|20\d\d)\b", segment)
        if match:
            return match.group(1)
    match = re.search(r"\b(19\d\d|20\d\d)\b", folder)
    return match.group(1) if match else None


# --- metadata lookups -------------------------------------------------------

def clean_album_for_lookup(album):
    """Strip edition/format suffixes so a lookup matches the canonical album.

    e.g. "Rust In Peace (Remastered)" -> "Rust In Peace",
         "Cryptic Writings [HDCD]"    -> "Cryptic Writings".
    Used only for API queries; the file's album tag is left untouched.
    """
    name = album
    while True:
        stripped = re.sub(r"\s*[\(\[][^()\[\]]*[)\]]\s*$", "", name).strip()
        stripped = re.sub(r"\s+(?:CD|Disc)\s*\d+\s*$", "", stripped,
                          flags=re.IGNORECASE).strip()
        if stripped == name or not stripped:
            break
        name = stripped
    return name or album


def lucene_escape(text):
    """Backslash-escape characters special to the MusicBrainz query parser.

    Album and artist go inside a quoted phrase; escaping the specials
    keeps a stray '!' or ':' from breaking the search.
    """
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/&|])', r"\\\1", text)


def mb_release_group(artist, album, is_va=False):
    """Return (release_group_id, year) for an album, or (None, None).

    `album` is expected pre-cleaned by clean_album_for_lookup. No
    primary-type filter (EPs, compilations and live albums must match).
    For a various-artists album the artist constraint is dropped.
    Prefers a result whose title equals the album exactly.
    """
    if is_va:
        query = 'releasegroup:"{0}"'.format(lucene_escape(album))
    else:
        query = 'artist:"{0}" AND releasegroup:"{1}"'.format(
            lucene_escape(artist), lucene_escape(album))
    url = ("https://musicbrainz.org/ws/2/release-group/?query="
           + urllib.parse.quote(query) + "&fmt=json&limit=8")
    data = http_get_json(url)
    if not data:
        return None, None
    groups = data.get("release-groups") or []
    if not groups:
        return None, None
    target = album.strip().lower()
    best = next(
        (g for g in groups if (g.get("title") or "").strip().lower() == target),
        groups[0])
    date = best.get("first-release-date") or ""
    year = date[:4] if re.match(r"\d{4}", date) else None
    return best.get("id"), year


def discogs_lookup(artist, album, is_va=False):
    """Return (genre, cover_url, master_id) from Discogs; each may be None.

    genre comes from the moderated "style" field. cover_url is a direct
    image URL, present only for token-authenticated requests. master_id
    enables the token-free cover route via discogs_master_image(). For
    various-artists albums the artist constraint is dropped.
    """
    params = {"release_title": album, "type": "release", "per_page": 8}
    if not is_va:
        params["artist"] = artist
    if DISCOGS_TOKEN:
        params["token"] = DISCOGS_TOKEN
    url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(
        params)
    data = http_get_json(url)
    if not data:
        return None, None, None
    styles, genres = Counter(), Counter()
    cover_url, master_id = None, None
    for result in (data.get("results") or []):
        for style in (result.get("style") or []):
            styles[style] += 1
        for genre in (result.get("genre") or []):
            genres[genre] += 1
        if cover_url is None:
            image = result.get("cover_image") or ""
            if image.startswith("http") and "spacer" not in image:
                cover_url = image
        if master_id is None and result.get("master_id"):
            master_id = result["master_id"]
    genre = None
    if styles:
        genre = styles.most_common(1)[0][0]
    elif genres:
        genre = genres.most_common(1)[0][0]
    return genre, cover_url, master_id


def discogs_master_image(master_id):
    """Return the primary cover-image URL for a Discogs master, or None.

    The Discogs search API omits image URLs unless the request is
    token-authenticated; the masters endpoint serves them either way,
    so this is the token-free route to a Discogs cover.
    """
    data = http_get_json(
        "https://api.discogs.com/masters/{0}".format(master_id))
    if not data:
        return None
    images = data.get("images") or []
    for image in images:
        if image.get("type") == "primary" and image.get("uri"):
            return image["uri"]
    return images[0].get("uri") if images else None


def download_image(url, dest):
    """Download an image to `dest`. Return True only for a real image file."""
    raw = http_get(url)
    if not raw or len(raw) < 2048:
        return False
    if not (raw[:3] == b"\xff\xd8\xff"               # JPEG
            or raw[:8] == b"\x89PNG\r\n\x1a\n"        # PNG
            or raw[:4] == b"RIFF"):                   # WebP
        return False
    dest.write_bytes(raw)
    return True


def fetch_cover(release_group_id, dest):
    """Download the Cover Art Archive front cover. Return True on success.

    Prefers the 1200px thumbnail: the full-size original can be tens of
    megabytes, wasteful to embed and large enough to overflow FLAC's
    16 MiB picture-block limit. Falls back to the original if absent.
    """
    base = "https://coverartarchive.org/release-group/{0}".format(
        release_group_id)
    return (download_image(base + "/front-1200", dest)
            or download_image(base + "/front", dest))


def normalize_cover(path):
    """Re-encode a cover to a bounded JPEG that is safe to embed.

    FLAC stores a picture in a metadata block capped at 16 MiB; an
    oversized image is silently dropped on embed (and bloats every
    track regardless). Downscale to at most 1000px wide and re-encode.
    Returns the normalized file, or the original if ffmpeg fails.
    """
    out = path.with_name(path.stem + ".norm.jpg")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(path),
           "-vf", "scale='min(1000,iw)':-1", "-q:v", "3", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and out.is_file() and out.stat().st_size > 1024:
        return out
    return path


# --- applying changes -------------------------------------------------------

def build_ffmpeg_cmd(src, dst, cover, metadata):
    """Construct the ffmpeg remux command (lossless -c copy)."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    if cover is not None:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v",
                "-map_metadata", "0", "-disposition:v:0", "attached_pic"]
    else:
        cmd += ["-map", "0"]
    cmd += ["-c", "copy"]
    if src.suffix.lower() == ".mp3":
        cmd += ["-id3v2_version", "3"]
    for key, value in metadata.items():
        cmd += ["-metadata", "{0}={1}".format(key, value)]
    cmd.append(str(dst))
    return cmd


def apply_changes(path, metadata, cover, expect_art):
    """Remux `path` with new metadata/art via a verified temp file.

    Returns True if the file was updated.
    """
    tmp = path.with_name(path.stem + ".fktmp" + path.suffix)
    cmd = build_ffmpeg_cmd(path, tmp, cover, metadata)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg failed: " + result.stderr.strip())
    check = ffprobe(tmp)
    if check is None:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("remuxed file is unreadable")
    if not any(s.get("codec_type") == "audio"
               for s in check.get("streams", [])):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("remuxed file has no audio stream")
    if expect_art and not has_cover_art(check):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("cover art missing from remuxed file")
    os.replace(tmp, path)
    return True


# --- per-album processing ---------------------------------------------------

def _norm(text):
    """Normalize a string for loose comparison."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_VARIOUS = ("various artists", "various", "va", "v.a.", "v/a")


def group_albums(files):
    """Group files into albums by folder + album tag.

    Returns a list of {artist, album, is_va, members} dicts; members are
    (path, data, tags) tuples. An album with no clear majority artist --
    or an album-artist tag of "Various Artists" -- is flagged is_va and
    later looked up by album alone rather than artist+album.
    """
    buckets: dict[tuple, list] = {}
    for path in files:
        data = ffprobe(path)
        if data is None:
            print("  ! unreadable: {0}".format(path), file=sys.stderr)
            continue
        tags = format_tags(data)
        album = tags.get("album", "")
        if not album:
            print("  ! no album tag, skipped: {0}".format(path),
                  file=sys.stderr)
            continue
        buckets.setdefault((str(path.parent), _norm(album)), []).append(
            (path, data, tags))

    records = []
    for members in buckets.values():
        album = Counter(t.get("album", "") for _, _, t in members
                        ).most_common(1)[0][0]
        album_artists = Counter(
            (t.get("album_artist") or t.get("albumartist"))
            for _, _, t in members
            if (t.get("album_artist") or t.get("albumartist")))
        artists = Counter(t["artist"] for _, _, t in members if t.get("artist"))
        is_va = False
        artist = ""
        if album_artists:
            artist = album_artists.most_common(1)[0][0]
        elif artists:
            top, count = artists.most_common(1)[0]
            if len(artists) >= 2 and count * 2 <= len(members):
                is_va = True
            else:
                artist = top
        if _norm(artist) in _VARIOUS or (not artist and not is_va):
            is_va = True
        if is_va:
            artist = "Various Artists"
        records.append({"artist": artist, "album": album,
                         "is_va": is_va, "members": members})
    return records


def process_album(record, work_dir, dry_run):
    """Look up an album and fill gaps in its files. Returns a stats Counter."""
    artist, album = record["artist"], record["album"]
    is_va, members = record["is_va"], record["members"]
    stats = Counter()

    needs_art = [m for m in members if not has_cover_art(m[1])]
    needs_genre = [m for m in members if not m[2].get("genre")]
    needs_date = [m for m in members if not m[2].get("date")]
    needs_track = [m for m in members if not m[2].get("track")]
    label = "{0}{1} - {2}".format("VA " if is_va else "", artist, album)
    if not (needs_art or needs_genre or needs_date or needs_track):
        print("ALBUM  {0}: complete, skipped".format(label))
        stats["albums_skipped"] += 1
        return stats

    lookup_album = clean_album_for_lookup(album)
    need_mb = bool(needs_art) or any(
        year_from_folder(m[0]) is None for m in needs_date)
    rg_id, mb_year = (None, None)
    if need_mb:
        rg_id, mb_year = mb_release_group(artist, lookup_album, is_va)
    genre, discogs_cover, discogs_master = (None, None, None)
    if needs_genre or needs_art:
        genre, discogs_cover, discogs_master = discogs_lookup(
            artist, lookup_album, is_va)
    if not needs_genre:
        genre = None

    cover, cover_src = None, "no"
    if needs_art:
        if rg_id:
            caa = work_dir / (rg_id + ".jpg")
            if fetch_cover(rg_id, caa):
                cover, cover_src = caa, "caa"
        if cover is None:
            url = discogs_cover
            if url is None and discogs_master:
                url = discogs_master_image(discogs_master)
            if url:
                dgc = work_dir / "dg_{0}.jpg".format(abs(hash(url)) % 10 ** 10)
                if download_image(url, dgc):
                    cover, cover_src = dgc, "discogs"
        if cover is not None:
            cover = normalize_cover(cover)

    print("ALBUM  {0}".format(label))
    print("  lookup: genre={0} cover={1} mb-year={2} ({3} tracks)".format(
        genre or "?", cover_src, mb_year or "?", len(members)))

    for path, data, tags in members:
        embed = cover is not None and not has_cover_art(data)
        metadata = {}
        if genre and not tags.get("genre"):
            metadata["genre"] = genre
        if not tags.get("date"):
            file_year = year_from_folder(path) or mb_year
            if file_year:
                metadata["date"] = file_year
        if not tags.get("track"):
            tn = track_from_filename(path)
            if tn is not None:
                metadata["track"] = str(tn)
        if not embed and not metadata:
            continue
        labels = (["+art"] if embed else []) + [
            "+{0}={1}".format(k, v) for k, v in sorted(metadata.items())]
        print("  {0:<14} {1}".format(",".join(labels), path.name))
        if dry_run:
            stats["would_change"] += 1
            continue
        try:
            apply_changes(path, metadata, cover if embed else None, embed)
            stats["changed"] += 1
            if embed:
                stats["art_embedded"] += 1
        except (RuntimeError, OSError) as exc:
            print("  ! FAILED {0}: {1}".format(path.name, exc), file=sys.stderr)
            stats["failed"] += 1
    return stats


def main(argv=None):
    require_python()
    parser = argparse.ArgumentParser(
        description="Fill missing audio tags and embed album cover art.")
    parser.add_argument("dirs", nargs="+", help="directories of audio files")
    parser.add_argument("--album", metavar="NAME",
                        help="only process albums whose tag contains NAME")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="process at most N albums")
    parser.add_argument("--dry-run", action="store_true",
                        help="report planned changes without writing")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print("error: required tool not found: " + tool, file=sys.stderr)
            return 2

    files = []
    for raw in args.dirs:
        root = Path(raw).expanduser()
        if not root.is_dir():
            print("skip (not a directory): {0}".format(root), file=sys.stderr)
            continue
        files += [p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXTS]

    records = group_albums(sorted(files))
    records.sort(key=lambda r: (r["artist"].lower(), r["album"].lower()))
    if args.album:
        needle = args.album.lower()
        records = [r for r in records if needle in r["album"].lower()]
    if args.limit:
        records = records[:args.limit]

    print("{0}: {1} album(s), {2} file(s)\n".format(
        "DRY RUN" if args.dry_run else "TAGGING",
        len(records), sum(len(r["members"]) for r in records)))

    totals = Counter()
    work_dir = Path(tempfile.mkdtemp(prefix="fieldkit-art-"))
    try:
        for record in records:
            totals.update(process_album(record, work_dir, args.dry_run))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print("\n== totals ==")
    for key in ("albums_skipped", "would_change", "changed",
                "art_embedded", "failed"):
        if totals[key]:
            print("  {0}: {1}".format(key, totals[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
