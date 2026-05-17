# optical/

Tools that turn an ordinary video file into a **playable optical disc
image** — an ISO you can burn and play in a standalone DVD or Blu-ray
player.

| Tool | Produces |
|---|---|
| `make_dvd_iso.py` | A DVD-Video ISO (MPEG-2 video, `VIDEO_TS` structure) |
| `make_bluray_iso.py` | A Blu-ray ISO (H.264 + AC3, `BDMV` structure) |

Both author a **single, menu-less title**: the finished disc auto-plays
the one video. `discutil.py` is the shared helper module they import —
it is not run directly.

## Pipeline

Each tool runs the same shape of pipeline:

1. `ffprobe` inspects the source — resolution, frame rate, audio.
2. `ffmpeg` transcodes to disc-compliant video and audio streams.
3. An authoring tool builds the disc folder structure.
4. An ISO image is written.

| Stage | DVD | Blu-ray |
|---|---|---|
| Transcode | `ffmpeg` → MPEG-2 program stream | `ffmpeg` → H.264 + AC3 elementary streams |
| Author | `dvdauthor` → `VIDEO_TS` | `tsMuxeR` → `BDMV` |
| Pack ISO | `xorriso` | `tsMuxeR` (writes the ISO itself) |

The Blu-ray tool lets `tsMuxeR` write the ISO directly because it
produces the UDF 2.50 filesystem that set-top Blu-ray players expect;
`xorriso`'s ISO support targets DVD-style filesystems.

## Dependencies

| Tool | Used by | Install on Oracle Linux 9 |
|---|---|---|
| `ffmpeg`, `ffprobe` | both | `dnf install ffmpeg` (needs the RPM Fusion repo; must include `libx264`) |
| `dvdauthor` | DVD | `dnf install dvdauthor` (RPM Fusion) |
| `xorriso` | DVD | `dnf install xorriso` |
| `tsMuxeR` | Blu-ray | Not packaged. Download a prebuilt binary from the maintained [`justdan96/tsMuxer`](https://github.com/justdan96/tsMuxer) releases. It must be a build that can write `.iso` output. |

Each tool checks for what it needs at startup and exits with install
hints if something is missing. If a binary is installed somewhere off
`PATH`, point at it explicitly in `.env` (see below).

## Configuration

Configuration is read from a repo-root `.env` file (see `example.env`).
Every value has a built-in default, so `.env` is optional — use it to
pin tool paths or change defaults per host:

```
cp example.env .env
```

Relevant keys: `FIELDKIT_FFMPEG`, `FIELDKIT_FFPROBE`,
`FIELDKIT_DVDAUTHOR`, `FIELDKIT_XORRISO`, `FIELDKIT_TSMUXER`,
`FIELDKIT_OUTPUT_DIR`, `FIELDKIT_WORK_DIR`, `FIELDKIT_DVD_STANDARD`,
`FIELDKIT_DVD_ASPECT`, `FIELDKIT_BLURAY_RESOLUTION`.

## Usage

```
# DVD — TV standard auto-detected from the source frame rate
python3.11 make_dvd_iso.py movie.mkv

# DVD — force PAL, 4:3, explicit output path
python3.11 make_dvd_iso.py movie.mkv --standard pal --aspect 4:3 -o /srv/iso/movie.iso

# Blu-ray — resolution auto-detected (1080 or 720)
python3.11 make_bluray_iso.py movie.mkv

# Blu-ray — force 720p
python3.11 make_bluray_iso.py movie.mkv --resolution 720

# See every command without running anything (works even if the
# authoring tools are not installed yet)
python3.11 make_dvd_iso.py movie.mkv --dry-run
```

On success the ISO path is printed to stdout; progress and the
commands being run go to stderr. `--keep-temp` preserves the
intermediate work directory for inspection.

## Known limitations

- **Single title, no menus.** By design — these build a disc that
  plays one video. Multi-title discs and menus are out of scope.
- **DVD size is not checked.** A long source at the DVD bitrate
  (~6 Mbit/s) can exceed the 4.7 GB single-layer limit. Trim the
  source first.
- **Blu-ray audio is re-encoded to AC3.** Stereo and 5.1 sources work;
  more than 5.1 channels is unsupported. Surround passthrough and
  lossless audio are possible future additions.
- **Verification status.** The `ffmpeg` transcode stages are verified.
  The `dvdauthor`, `xorriso`, and `tsMuxeR` stages are written but not
  yet run end-to-end — verify on the first real build.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Bad input or usage (missing/non-video file, bad argument) |
| 2 | A required tool is missing, or a pipeline step failed |
