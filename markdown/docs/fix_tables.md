# fix_tables.py

## Purpose

Hand-edited Markdown tables drift: cells of different widths, a missing pipe at the end of a
row, a row with one cell too few. They still render, but they are hard to read and edit as
text. `fix_tables.py` rebuilds every pipe table in a file so each column is one width and every
row has the same cells, without touching the cell text.

## What it changes

- Every cell is padded with spaces to its column's widest cell (at least 3).
- Every row starts with `| ` and ends with ` |`, cells separated by ` | `.
- The delimiter row is redrawn as dashes the column's width, **keeping the alignment colons**
  (`:---`, `---:`, `:-:`). Right-aligned columns are padded on the left, centred columns on
  both sides.
- A row with fewer cells gets empty cells. A row with more cells widens the whole table (an
  empty column is added to the others) rather than dropping text.
- With `--bold-headers`, each non-empty header cell becomes `**text**`. A cell that is already
  bold is left as it is, so running the tool twice gives the same result.

Nothing else in the file changes: line endings (LF or CRLF), the final newline, text between
tables, and the indentation of an indented table are all kept.

## What counts as a table

GitHub-flavored Markdown's rule: a line containing `|`, followed by a delimiter row with the
**same number of cells**. The body runs until a blank line or a line without a `|`.

- `a | b` over `---` is a heading underline, not a table (cell counts differ), and is left alone.
- Tables inside fenced code blocks (```` ``` ```` or `~~~`) are left alone.
- `\|` is a pipe inside a cell, not a cell boundary.

## Edge cases and known limits

- **Pipes inside inline code.** GitHub splits cells on `` `a|b` `` too, so this tool does the
  same. Write `\|` inside code in a table.
- **Wide characters.** CJK characters and most emoji count as two columns, so the table lines up
  in a terminal or monospace editor. Some emoji sequences (flags, skin tones, ZWJ sequences)
  still render at a width the standard library cannot predict.
- **Blockquoted tables** (`> | a | b |`) are not recognised and are left alone.
- **Lines after a table without a blank line** that contain a `|` are treated as table rows, as
  GitHub does.

## Design decisions

- Standard library only, Python 3.9+, so it runs on any of the fleet's hosts with no setup.
- Never edits cell text (except `--bold-headers`), so it is safe to run with `--in-place` on
  large generated files. Checked on a 1,685-line index of 990 table rows: every row's cells
  parsed identically before and after, and a second run changed nothing.
- `--check` exists for pre-commit hooks and CI: it writes nothing and exits 1 when a file would
  change.
