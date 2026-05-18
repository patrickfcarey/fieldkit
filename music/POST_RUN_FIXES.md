# Post-Run Manual Fixes

Issues identified from the dry-run on 2026-05-17 that need manual correction
after `tag_music.py` completes its real run.

---

## 1. track=0 — Two files with "00 -" prefix filenames

The tagger parsed `00` as a track number and will write `track=0`, which most
players don't handle well. Fix: clear the track tag on these two files.

| File | Notes |
|------|-------|
| `Powerman 5000/Powerman 5000 - Dracula 2000 Soundtrack - 00 - Ultra-mega.mp3` | Will be tagged — needs fix |
| `1_youtube_rips/Tom Petty and the Heartbreakers - Damn the Torpedoes - 00 - Don't Do Me Like That.mp3` | No album tag, tagger skips it — no fix needed |

**Fix command (run after the real tagging run):**
```bash
F="/tank/backups/media_3x/music/playlists/lib/Powerman 5000/Powerman 5000 - Dracula 2000 Soundtrack - 00 - Ultra-mega.mp3"
ffmpeg -v error -y -i "$F" -c copy -metadata track="" "${F%.mp3}.fktmp.mp3" \
  && mv "${F%.mp3}.fktmp.mp3" "$F" && echo "fixed"
```

---

## 2. Wrong date — 8 albums got a MusicBrainz reissue year instead of original

MusicBrainz matched a reissue release group for these albums, so the
`first-release-date` it returned was wrong. All 8 had blank date tags so
the bad year was written. Correct dates are listed below.

| Album | Written (wrong) | Should be |
|-------|----------------|-----------|
| Calvin Harris - Motion | 2014 | 2014 ✓ (this one is actually correct) |
| Disturbed - Asylum | 2010 | 2010 ✓ (correct) |
| Evile - Skull | 2013 | 2013 ✓ (correct) |
| Opeth - In Cauda Venenum (Bonus Tracks) | 2019 | 2019 ✓ (correct) |
| Opeth - In Cauda Venenum (English Version) | 2019 | 2019 ✓ (correct) |
| Opeth - In Cauda Venenum (Swedish Version) | 2019 | 2019 ✓ (correct) |
| Simple Plan - Get Your Heart On! (Deluxe) | 2011 | 2011 ✓ (correct) |
| Taking Back Sunday - Happiness Is | 2014 | 2014 ✓ (correct) |

> **Note:** After verifying against the actual albums, all 8 years appear to be
> correct original release years — the concern was that 2010+ looked like
> reissue bait, but these are genuinely post-2010 albums. No manual fixes
> needed here.

**Separately confirmed wrong (from spot-check of albums already having a date tag):**

| Album | MB returned | Correct year | Action |
|-------|------------|--------------|--------|
| Deep Purple - Made in Japan | 2014 | 1972 | File already had date tag — NOT written by tagger. No fix needed. |
| Fleetwood Mac - Fm(Us) | 2020 | unclear | File already had date tag — NOT written by tagger. No fix needed. |
| Linkin Park - Hybrid Theory | 2010+ | 2000 | File already had date tag — NOT written by tagger. No fix needed. |

---

## Summary

| Issue | Count | Action needed |
|-------|-------|--------------|
| track=0 written | 2 files | Clear track tag (command above) |
| Wrong date written | 0 albums | All 8 verified correct after cross-check |
| Wrong date risk (existing tag protected) | 3+ albums | No action — existing tags were never overwritten |
