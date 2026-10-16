# markdown

Tools for Markdown files.

| Tool            | What it does                                                                             |
| --------------- | ---------------------------------------------------------------------------------------- |
| `fix_tables.py` | Lines up pipe tables: padded cells, pipes at both ends, even rows, optional bold headers |

## fix_tables.py

```bash
python3 markdown/fix_tables.py notes.md                  # print the fixed file
python3 markdown/fix_tables.py --in-place docs/*.md      # rewrite the files
python3 markdown/fix_tables.py --check docs/*.md         # exit 1 if any file would change
python3 markdown/fix_tables.py --bold-headers notes.md   # also wrap header cells in **...**
cat notes.md | python3 markdown/fix_tables.py            # stdin to stdout
python3 markdown/fix_tables.py --self-test               # built-in checks
```

Before:

```text
Name|Size|Notes
:--|--:|---
alpha|1|first
beta-long-name|12345
```

After `--bold-headers`:

```text
| **Name**       | **Size** | **Notes** |
| :------------- | -------: | --------- |
| alpha          |        1 | first     |
| beta-long-name |    12345 |           |
```

Details, edge cases and limits: [`docs/fix_tables.md`](docs/fix_tables.md).

## Tests

```bash
python3 -m unittest discover -s markdown/tests
```
