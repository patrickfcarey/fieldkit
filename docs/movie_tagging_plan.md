# Movie Tagging Plan

Plan for an automated tool that adds **chapter markers** to a directory of
video files (TV episodes, typically animated series), so downstream disc
authoring (`make_dvd_iso.py` / `make_bluray_iso.py`) can carry per-episode
chapters.

**Status:** planning — three decisions pending (see *Open decisions*).

## Goal

Batch-process a directory of episode files. Files that already have
chapters are left alone; files without chapters get chapter markers
generated automatically, with no per-file interaction.

## Scope and behavior

- Input: a directory of video files (MKV, MP4, and possibly AVI).
- For each file, detect whether it already has chapter markers:
  - **2 or more chapters** — already done; skip, leave untouched.
  - **0 or 1 chapters** — treated as untagged; process it.
- Runs unattended as a batch. No per-file prompts.
- Produces a report listing what each file received.

## Detection method

- Chapters are placed at **act breaks**.
- Act breaks are found by detecting **fade-to-black** segments with
  ffmpeg's `blackdetect` filter — animated series almost always fade to
  black at each act break.
- A chapter mark is placed where the picture resumes after each fade.
- A chapter is always placed at `00:00:00`.
- A minimum spacing between marks suppresses spurious detections (e.g. a
  brief mid-scene black frame).
- Detection is calibrated on one sample episode before the full batch
  run, to confirm the show's fades are being caught.

## Open decisions

These must be answered before the batch can run unattended.

1. **File handling.** MKV chapters can be written *in place* (metadata
   only, no re-encode, reversible). MP4 cannot be edited in place — it
   must be rewritten as a new file (a lossless repackage).
   *Decision needed:* in-place edits on the MKVs, or write every tagged
   file as a copy into a separate output folder with all originals left
   untouched?

2. **AVI files.** AVI cannot store chapters at all; the only way to give
   an AVI chapters is to repackage it into an MKV.
   *Decision needed:* convert AVI files to MKV so they can be tagged, or
   skip them and leave them as-is?

3. **Fallback.** Some files may not fade to black (a show that hard-cuts
   between acts), so detection finds nothing usable.
   *Decision needed:* leave such a file without chapters and flag it in
   the report, or fall back to evenly spaced chapters (e.g. one every
   5 minutes) so every file still gets something?

## Defaults

Applied unless changed:

- A chapter is always placed at the start (`00:00:00`).
- Detected marks land where the picture resumes after each fade.
- Files with 2 or more existing chapters are skipped as already done.
- Chapters are named `Chapter 01`, `Chapter 02`, and so on.
- The run produces a report listing every file and the chapters it
  received.

## Tooling

- Implemented as a fieldkit script (e.g. `tag_chapters.py`) so the batch
  is repeatable on future shows.
- Dependencies: `ffmpeg` / `ffprobe` for detection and MP4 rewrites;
  `mkvtoolnix` (`mkvpropedit`) for in-place MKV chapter writes.
- Intended to run **before** `make_dvd_iso.py` / `make_bluray_iso.py`.
