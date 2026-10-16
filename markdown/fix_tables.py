#!/usr/bin/env python3
# Name: fix_tables.py
# Description: Lines up the pipe tables in Markdown files: every cell padded to its column's
#              width, a pipe at both ends of every row, every row the same number of cells,
#              and an optional **bold** header row.
# Usage: python3 fix_tables.py [--in-place | --check] [--bold-headers] [FILE ...]
#        (no FILE, or FILE "-", reads standard input and writes standard output)
# Inputs: Markdown files (UTF-8)
# Outputs: the fixed Markdown on standard output, or the files rewritten with --in-place.
#          --check writes nothing and exits 1 when any file would change.

# Environment:
#   Tested:
#     - Oracle Linux Server 9.7 (WSL2), Python 3.9.25
#   Expected:
#     - any Linux, macOS or Windows with Python 3.9 or newer
#   Dependencies:
#     - python >= 3.9 (standard library only)

# Assumptions:
#   - A table is a header row, then a delimiter row (---, :--, --:, :-:), then body rows,
#     as GitHub-flavored Markdown defines it. Anything else is left exactly as it was.
#   - Files are UTF-8.
# Failure Modes:
#   - File not found or not UTF-8: reported on stderr, exit 2, other files still processed.
# Notes:
#   - Only the spaces around cells, the pipes at the row ends and the delimiter dashes change.
#     Cell text is never edited, except that --bold-headers wraps header cells in **...**.
#   - Tables inside fenced code blocks (``` or ~~~) are left alone.
#   - A pipe written as \| stays inside its cell, as in GitHub-flavored Markdown.
#   - Wide characters (CJK, most emoji) count as two columns, so tables line up in a terminal.
#   - Short rows get empty cells added; a row with extra cells widens the table rather than
#     losing text.
#   - Run the self-test with: python3 fix_tables.py --self-test

import argparse
import re
import sys
import unicodedata


# A delimiter cell: optional colon, at least one dash, optional colon.
DELIMITER_CELL = re.compile(r"^:?-+:?$")

# A fence opens or closes a code block: three or more backticks or tildes.
FENCE = re.compile(r"^\s*(```+|~~~+)")


def split_row(line):
    """Split one table row into its cell texts, stripped of surrounding spaces.

    The pipes at the row's ends are optional in Markdown, so they are dropped if present.
    A backslash-escaped pipe (\\|) is part of the cell's text, not a cell boundary.
    """
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]

    cells = []
    current = ""
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            # Keep the escape and the escaped character together, untouched.
            current += text[i:i + 2]
            i += 2
            continue
        if char == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += char
        i += 1
    cells.append(current.strip())
    return cells


def is_delimiter_row(line):
    """True when the line is a table delimiter row such as |---|:--:|."""
    if "-" not in line:
        return False
    cells = split_row(line)
    return all(DELIMITER_CELL.match(cell) for cell in cells)


def display_width(text):
    """How many terminal columns the text takes: wide characters count 2, combining marks 0."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def alignment_of(delimiter_cell):
    """Read a delimiter cell's alignment: 'left', 'right', 'center' or None (unspecified)."""
    starts = delimiter_cell.startswith(":")
    ends = delimiter_cell.endswith(":")
    if starts and ends:
        return "center"
    if ends:
        return "right"
    if starts:
        return "left"
    return None


def pad(text, width, alignment):
    """Pad the cell text with spaces to the column width, honouring the column's alignment."""
    missing = width - display_width(text)
    if alignment == "right":
        return " " * missing + text
    if alignment == "center":
        left = missing // 2
        return " " * left + text + " " * (missing - left)
    return text + " " * missing


def delimiter_cell(width, alignment):
    """Build a delimiter cell exactly `width` columns wide that keeps the alignment colons."""
    if alignment == "center":
        return ":" + "-" * (width - 2) + ":"
    if alignment == "right":
        return "-" * (width - 1) + ":"
    if alignment == "left":
        return ":" + "-" * (width - 1)
    return "-" * width


def make_bold(text):
    """Wrap a header cell in **...** unless it is empty or already bold."""
    if text == "" or (text.startswith("**") and text.endswith("**") and len(text) >= 4):
        return text
    return "**" + text + "**"


def format_table(lines, bold_headers):
    """Return the table's lines rebuilt with every column the same width.

    lines[0] is the header row, lines[1] the delimiter row, the rest are body rows.
    """
    # Keep the table's indentation (a table inside a list item is indented).
    indent = lines[0][:len(lines[0]) - len(lines[0].lstrip())]

    header = split_row(lines[0])
    alignments = [alignment_of(cell) for cell in split_row(lines[1])]
    body = [split_row(line) for line in lines[2:]]

    if bold_headers:
        header = [make_bold(cell) for cell in header]

    # Every row gets the same number of cells: the most any row has.
    column_count = max(len(row) for row in [header, alignments] + body)
    for row in [header] + body:
        row.extend([""] * (column_count - len(row)))
    alignments.extend([None] * (column_count - len(alignments)))

    # A column is as wide as its widest cell, and at least 3 so the delimiter is valid
    # (":-:" needs 3 characters).
    widths = []
    for column in range(column_count):
        widest = max(display_width(row[column]) for row in [header] + body)
        widths.append(max(widest, 3))

    def build(cells):
        return indent + "| " + " | ".join(cells) + " |"

    result = [build([pad(header[c], widths[c], alignments[c]) for c in range(column_count)])]
    result.append(build([delimiter_cell(widths[c], alignments[c]) for c in range(column_count)]))
    for row in body:
        result.append(build([pad(row[c], widths[c], alignments[c]) for c in range(column_count)]))
    return result


def fix_text(text, bold_headers=False):
    """Find every pipe table in the Markdown text and line it up. Everything else is unchanged."""
    # Remember the line ending style and whether the file ended in a newline, so both survive.
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)

    output = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]

        if FENCE.match(line):
            in_fence = not in_fence
            output.append(line)
            i += 1
            continue

        # A table starts where a row with a pipe is followed by a delimiter row with the same
        # number of cells. (With a different count, "a | b" over "---" is a heading, not a table.)
        starts_table = (
            not in_fence
            and "|" in line
            and i + 1 < len(lines)
            and is_delimiter_row(lines[i + 1])
            and len(split_row(line)) == len(split_row(lines[i + 1]))
        )
        if not starts_table:
            output.append(line)
            i += 1
            continue

        # The body runs until a blank line or a line without a pipe.
        end = i + 2
        while end < len(lines) and lines[end].strip() != "" and "|" in lines[end]:
            end += 1

        output.extend(format_table(lines[i:end], bold_headers))
        i = end

    return newline.join(output)


def run_self_test():
    """Check the tool against small worked examples. Exit 0 when every check passes."""
    checks = [
        (
            "uneven columns are padded",
            "| a | bb |\n|-|-|\n| ccc | d |\n",
            "| a   | bb  |\n| --- | --- |\n| ccc | d   |\n",
            False,
        ),
        (
            "missing outer pipes are added",
            "a | b\n--|--\n1 | 2\n",
            "| a   | b   |\n| --- | --- |\n| 1   | 2   |\n",
            False,
        ),
        (
            "alignment colons are kept and honoured",
            "| L | C | R |\n|:-|:-:|-:|\n| long | x | 12345 |\n",
            "| L    |  C  |     R |\n| :--- | :-: | ----: |\n| long |  x  | 12345 |\n",
            False,
        ),
        (
            "short rows get empty cells",
            "| a | b | c |\n|---|---|---|\n| 1 |\n",
            "| a   | b   | c   |\n| --- | --- | --- |\n| 1   |     |     |\n",
            False,
        ),
        (
            "an escaped pipe stays in its cell",
            "| cmd | note |\n|---|---|\n| a \\| b | x |\n",
            "| cmd    | note |\n| ------ | ---- |\n| a \\| b | x    |\n",
            False,
        ),
        (
            "headers are made bold once",
            "| name | **size** |\n|---|---|\n| x | 1 |\n",
            "| **name** | **size** |\n| -------- | -------- |\n| x        | 1        |\n",
            True,
        ),
        (
            "tables in code fences are left alone",
            "```\n| a | b |\n|-|-|\n```\n",
            "```\n| a | b |\n|-|-|\n```\n",
            False,
        ),
        (
            "wide characters count two columns",
            "| k | v |\n|---|---|\n| 日本 | x |\n",
            "| k    | v   |\n| ---- | --- |\n| 日本 | x   |\n",
            False,
        ),
        (
            "text around a table is untouched and an indented table keeps its indent",
            "Intro | not a table\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\nAfter.\n",
            "Intro | not a table\n\n  | a   | b   |\n  | --- | --- |\n  | 1   | 2   |\nAfter.\n",
            False,
        ),
        (
            "a heading underline is not a table delimiter",
            "a | b\n---\n",
            "a | b\n---\n",
            False,
        ),
        (
            "CRLF line endings survive",
            "| a | b |\r\n|-|-|\r\n| 1 | 2 |\r\n",
            "| a   | b   |\r\n| --- | --- |\r\n| 1   | 2   |\r\n",
            False,
        ),
    ]

    failures = 0
    for name, given, expected, bold in checks:
        got = fix_text(given, bold_headers=bold)
        again = fix_text(got, bold_headers=bold)
        if got != expected:
            failures += 1
            print("FAIL  " + name)
            print("      expected: " + repr(expected))
            print("      got:      " + repr(got))
        elif again != got:
            failures += 1
            print("FAIL  " + name + " (running it twice changes the output)")
        else:
            print("ok    " + name)

    print("{} of {} checks passed".format(len(checks) - failures, len(checks)))
    return 0 if failures == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Line up the pipe tables in Markdown files.",
    )
    parser.add_argument("files", nargs="*", help="Markdown files; none or '-' reads stdin")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-i", "--in-place", action="store_true",
                      help="rewrite each file instead of printing it")
    mode.add_argument("--check", action="store_true",
                      help="change nothing; exit 1 and name each file that would change")
    parser.add_argument("-b", "--bold-headers", action="store_true",
                        help="wrap every header cell in **...**")
    parser.add_argument("--self-test", action="store_true", help="run the built-in checks")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    files = args.files or ["-"]
    exit_code = 0

    for path in files:
        if path == "-":
            if args.in_place:
                print("fix_tables: --in-place needs a file, not standard input", file=sys.stderr)
                return 2
            original = sys.stdin.read()
            fixed = fix_text(original, args.bold_headers)
            if args.check:
                if fixed != original:
                    print("would change: <stdin>")
                    exit_code = max(exit_code, 1)
            else:
                sys.stdout.write(fixed)
            continue

        try:
            # newline="" keeps CRLF line endings exactly as they are in the file.
            with open(path, encoding="utf-8", newline="") as handle:
                original = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            print("fix_tables: {}: {}".format(path, error), file=sys.stderr)
            exit_code = 2
            continue

        fixed = fix_text(original, args.bold_headers)

        if args.check:
            if fixed != original:
                print("would change: " + path)
                exit_code = max(exit_code, 1)
        elif args.in_place:
            if fixed != original:
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(fixed)
                print("fixed: " + path)
        else:
            sys.stdout.write(fixed)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
