#!/usr/bin/env python3
"""Stress-test tag_music.py against 100 deliberately tricky albums.

Creates a temp directory of silent 1-second MP3 stubs (tagged with
artist/album/title but missing genre, date, and cover art), then runs
tag_music.py --dry-run so every lookup path is exercised without
touching real files or writing anything.

Rate limiting: all API calls are made by tag_music.py, which enforces
the per-host throttle declared in its THROTTLE dict (1.1 s/req for
MusicBrainz, 1.5 s/req for Discogs). This test adds no extra delay on
top of that; the throttle is the floor, not a bypass. Expected wall
time for the full 100-album run is ~8-10 minutes.

Usage:
    python3 music/tests/run_target_test.py [--limit N]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tag_music.py"

# 100 albums chosen to stress every code path:
#   - Various-artists compilations (is_va detection)
#   - Special characters in names (, !, /, &, ?, ...)
#   - Non-ASCII / Unicode (Björk, Motörhead, Rammstein, ...)
#   - Edition / remaster suffixes (clean_album_for_lookup stripping)
#   - Multi-disc sets (CD1/Disc 2 suffix stripping)
#   - Self-titled albums (artist == album)
#   - Classical with long descriptive titles
#   - Live albums
#   - Common/ambiguous titles ("Greatest Hits", "Gold")
#   - Non-English titles
#   - Punctuation-heavy titles (ellipsis, parens, brackets)
#   - Single-character / very short titles
#   - Very long titles
#   - Roman-numeral-only titles
#   - Albums that are unlikely to exist in MB/Discogs (graceful miss)
# fmt: off
ALBUMS = [
    # --- Various Artists -------------------------------------------------------
    ("Various Artists",  "Now That's What I Call Music! 50",          True),
    ("Various Artists",  "Pulp Fiction: Music From The Motion Picture", True),
    ("Various Artists",  "The Crow: Original Motion Picture Soundtrack", True),
    ("Various Artists",  "Trainspotting (Music From The Motion Picture)", True),
    ("Various Artists",  "Buena Vista Social Club",                   True),

    # --- Special characters in artist name ------------------------------------
    ("Guns N' Roses",    "Appetite for Destruction",                  False),
    ("AC/DC",            "Back in Black",                             False),
    ("P!nk",             "Misundaztood",                              False),
    ("!!!",              "Myth Takes",                                False),
    ("Panic! at the Disco", "A Fever You Can't Sweat Out",            False),

    # --- Non-ASCII / Unicode --------------------------------------------------
    ("Björk",            "Post",                                      False),
    ("Björk",            "Homogenic",                                 False),
    ("Sigur Rós",        "Ágætis byrjun",                             False),
    ("Motörhead",        "Ace of Spades",                             False),
    ("Queensrÿche",      "Operation: Mindcrime",                      False),
    ("Mötley Crüe",      "Dr. Feelgood",                              False),
    ("Rammstein",        "Mutter",                                    False),

    # --- Edition / remaster suffixes ------------------------------------------
    ("Nirvana",          "Nevermind (Remastered)",                    False),
    ("Pink Floyd",       "The Dark Side of the Moon [2003 SACD Remaster]", False),
    ("U2",               "Achtung Baby [Super Deluxe Edition]",       False),
    ("Megadeth",         "Rust In Peace (Remastered)",                False),
    ("Pearl Jam",        "Ten (Legacy Edition)",                      False),
    ("David Bowie",      "The Rise and Fall of Ziggy Stardust and the Spiders from Mars [2012 Remaster]", False),

    # --- Multi-disc sets -------------------------------------------------------
    ("Pink Floyd",       "The Wall (Disc 1)",                         False),
    ("Pink Floyd",       "The Wall (Disc 2)",                         False),
    ("The Rolling Stones", "Exile on Main St. [Disc 2]",              False),
    ("The Smashing Pumpkins", "Mellon Collie and the Infinite Sadness CD1", False),
    ("The Smashing Pumpkins", "Mellon Collie and the Infinite Sadness CD2", False),

    # --- Self-titled ----------------------------------------------------------
    ("Weezer",           "Weezer",                                    False),
    ("Metallica",        "Metallica",                                 False),
    ("Led Zeppelin",     "Led Zeppelin",                              False),
    ("The Beatles",      "The Beatles",                               False),
    ("Radiohead",        "Pablo Honey",                               False),

    # --- Classical ------------------------------------------------------------
    ("Ludwig van Beethoven", "Symphony No. 9 in D Minor, Op. 125",   False),
    ("Johann Sebastian Bach", "The Goldberg Variations",              False),
    ("Antonio Vivaldi",  "The Four Seasons",                          False),
    ("Pyotr Ilyich Tchaikovsky", "The Nutcracker Suite",             False),
    ("Miles Davis",      "Kind of Blue",                              False),
    ("John Coltrane",    "A Love Supreme",                            False),
    ("The Dave Brubeck Quartet", "Time Out",                          False),

    # --- Live albums ----------------------------------------------------------
    ("Nirvana",          "Unplugged in New York",                     False),
    ("The Who",          "Live at Leeds",                             False),
    ("Johnny Cash",      "At Folsom Prison",                          False),
    ("Pearl Jam",        "Alive",                                     False),
    ("Metallica",        "S&M",                                       False),

    # --- Ambiguous / common titles --------------------------------------------
    ("Queen",            "Greatest Hits",                             False),
    ("Bruce Springsteen", "Greatest Hits",                            False),
    ("ABBA",             "Gold: Greatest Hits",                       False),
    ("Bob Dylan",        "The Essential Bob Dylan",                   False),
    ("David Bowie",      "Best of Bowie",                             False),

    # --- Punctuation-heavy titles ---------------------------------------------
    ("Metallica",        "...And Justice for All",                    False),
    ("Oasis",            "(What's the Story) Morning Glory?",         False),
    ("Britney Spears",   "...Baby One More Time",                     False),
    ("Megadeth",         "Peace Sells... but Who's Buying?",          False),
    ("DJ Shadow",        "Endtroducing.....",                         False),

    # --- Non-English titles ---------------------------------------------------
    ("Sigur Rós",        "( )",                                       False),
    ("Rammstein",        "Reise, Reise",                              False),
    ("Arcade Fire",      "Neon Bible",                                False),
    ("Zucchero",         "Oro Incenso & Birra",                       False),
    ("Portishead",       "Dummy",                                     False),

    # --- Hip-hop / rap --------------------------------------------------------
    ("Eminem",           "The Marshall Mathers LP",                   False),
    ("Jay-Z",            "The Blueprint",                             False),
    ("Wu-Tang Clan",     "Enter the Wu-Tang (36 Chambers)",           False),
    ("Nas",              "Illmatic",                                  False),
    ("The Notorious B.I.G.", "Ready to Die",                         False),
    ("Kendrick Lamar",   "good kid, m.A.A.d city",                   False),
    ("Kendrick Lamar",   "DAMN.",                                     False),
    ("Pusha T",          "My Name Is My Name",                        False),

    # --- Electronic -----------------------------------------------------------
    ("Daft Punk",        "Random Access Memories",                    False),
    ("Daft Punk",        "Discovery",                                 False),
    ("Aphex Twin",       "Selected Ambient Works 85-92",              False),
    ("Boards of Canada", "Music Has the Right to Children",           False),
    ("Massive Attack",   "Mezzanine",                                 False),
    ("The xx",           "xx",                                        False),

    # --- Short / single-character titles --------------------------------------
    ("Damien Rice",      "O",                                         False),
    ("Moby",             "18",                                        False),
    ("Adele",            "21",                                        False),
    ("Adele",            "25",                                        False),

    # --- Roman numeral / number titles ----------------------------------------
    ("Rush",             "2112",                                      False),
    ("Van Halen",        "1984",                                      False),
    ("Taylor Swift",     "1989",                                      False),
    ("Led Zeppelin",     "Led Zeppelin IV",                           False),
    ("Led Zeppelin",     "Led Zeppelin III",                          False),

    # --- Very long titles -----------------------------------------------------
    ("Stevie Wonder",    "Songs in the Key of Life",                  False),
    ("Marvin Gaye",      "What's Going On",                           False),
    ("Bob Dylan",        "Blood on the Tracks",                       False),
    ("Fleetwood Mac",    "Rumours",                                   False),
    ("Bruce Springsteen", "Born to Run",                              False),

    # --- Obscure / expect graceful lookup miss --------------------------------
    ("Unknown Local Band XYZ", "The Demo Sessions Vol. 1",            False),
    ("Nonexistent Artist 99",  "Album That Does Not Exist",           False),

    # --- Misc interesting cases -----------------------------------------------
    ("Johnny Cash",      "American IV: The Man Comes Around",         False),
    ("Pink Floyd",       "Wish You Were Here",                        False),
    ("Radiohead",        "OK Computer",                               False),
    ("Radiohead",        "In Rainbows",                               False),
    ("The Strokes",      "Is This It",                                False),
    ("Boards of Canada", "Geogaddi",                                  False),
    ("Aphex Twin",       "Richard D. James Album",                    False),
    ("Nine Inch Nails",  "The Downward Spiral",                       False),
    ("Tool",             "Lateralus",                                 False),
    ("Nick Cave & the Bad Seeds", "Murder Ballads",                   False),
]
# fmt: on

assert len(ALBUMS) == 100, "Expected 100 test albums, got {0}".format(len(ALBUMS))


def make_stub(path: Path, artist: str, album: str, title: str) -> bool:
    """Create a 1-second silent MP3 with the given tags via ffmpeg."""
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "1", "-q:a", "9",
        "-metadata", "artist={0}".format(artist),
        "-metadata", "album={0}".format(album),
        "-metadata", "title={0}".format(title),
        # leave genre, date, track blank so the tagger has work to do
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


def build_fixture(root: Path, albums: list) -> Path:
    music_dir = root / "music"
    music_dir.mkdir()
    print("Building {0} album stubs in {1} ...".format(len(albums), music_dir))
    created, failed = 0, 0
    for artist, album, _is_va in albums:
        safe = "".join(
            c if c.isalnum() or c in " -_." else "_"
            for c in "{0} - {1}".format(artist, album)
        )[:80]
        album_dir = music_dir / safe
        album_dir.mkdir(exist_ok=True)
        for i in range(1, 3):  # 2 tracks per album
            stub = album_dir / "track_{0:02d}.mp3".format(i)
            title = "Track {0}".format(i)
            if make_stub(stub, artist, album, title):
                created += 1
            else:
                print("  ! ffmpeg failed: {0}".format(stub), file=sys.stderr)
                failed += 1
    print("Created {0} stubs ({1} failed)\n".format(created, failed))
    return music_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, metavar="N",
                        help="process only the first N albums")
    args = parser.parse_args()

    albums = ALBUMS[:args.limit] if args.limit else ALBUMS
    tmp = tempfile.mkdtemp(prefix="fieldkit-targettest-")
    try:
        music_dir = build_fixture(Path(tmp), albums)
        print("Running tag_music.py --dry-run against {0} albums...\n".format(
            len(albums)))
        py = shutil.which("python3.11") or sys.executable
        cmd = [
            py, str(SCRIPT),
            str(music_dir),
            "--dry-run",
        ]
        result = subprocess.run(cmd)
        return result.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
