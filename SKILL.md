---
name: pdf-toc
description: Give a PDF a real table of contents — a nested bookmark outline plus a clickable printed TOC page — and prove the pages were not altered. Use when a PDF has no bookmarks, when its printed 目录/TOC page is dead text, or when text extraction returns mojibake because CJK subset fonts carry no /ToUnicode (then section titles must be read from rendered page images, not from copy-paste).
license: AGPL-3.0-or-later
compatibility: Python 3.9+ with pypdf and PyMuPDF (`python -m pip install pypdf pymupdf`). Windows, macOS, Linux. No Office, no Ghostscript, no browser. Reading mojibake documents additionally needs the ability to look at rendered PNG pages (the agent's own vision).
allowed-tools: Bash(python *) Bash(python3 *)
metadata:
  when_to_use: A PDF must become navigable. Either it has no bookmark outline, or its printed table-of-contents page is not clickable. The hard case is a Chinese/Japanese PDF whose text extraction is garbage (font subset without ToUnicode) — there the headings may only be read from rendered images.
  hosts: DSH, Claude Code, Codex, Cursor
  homepage: https://github.com/ZihanZhang114514/pdf-toc
---

# pdf-toc — a real table of contents for a PDF

Three scripts, one JSON spec, three guarantees:

```
probe_pdf.py   →  is the text layer usable?  where are the headings?   (or: render pages to PNG)
make_toc.py    →  outline bookmarks + clickable printed TOC page, from the spec
verify_toc.py  →  outline/link assertions + all pages render pixel-identical
```

Output is always a **new file**. The source PDF is never touched, because the one
thing you cannot recover here is a mangled source.

## Non-negotiables

1. **Never ship without `verify_toc.py` printing `ALL CHECKS PASSED`.** It
   re-reads the file, compares every bookmark against the spec, resolves every
   link destination, and pixel-compares all pages at 72 dpi.
2. **Never invent a section title.** Read it off the document — from the text
   layer when it is readable, from a rendered page image when it is not. A
   translation of the English datasheet is *not* the Chinese document's own
   wording (see "Titles lie" below).
3. **Never trust a Chinese PDF's text layer before probing it.** Copy-paste and
   every extractor share the same broken font mapping.

## First 30 seconds

```bash
python -m pip install pypdf pymupdf
python scripts/probe_pdf.py IN.pdf
```

Read the verdict line:

| `text layer:` | meaning | next |
|---|---|---|
| `ok` | extraction returns real characters | normal workflow |
| `garbled` | font subsets without `/ToUnicode`; codepoints are glyph IDs | render-and-read workflow |
| `empty` | scanned or vector-only pages | render-and-read workflow |

`garbled` looks like Tibetan/Arabic/Armenian/Thai characters in a Chinese
document, e.g. `Ϫ۩૦๏` for 修订历史. That is a glyph index, not text. Do not try to
decode it with a substitution table — see `references/pitfalls.md`.

## Workflow A — text layer is readable

```bash
python scripts/probe_pdf.py IN.pdf --min-size 12        # heading candidates
python scripts/probe_pdf.py IN.pdf --render 2           # look at the TOC page
```

1. List the headings from the probe output (page, `y_top`, size, text).
2. If the document has a printed TOC page, extract it in layout mode to recover
   the two-column structure and page numbers — digits extract fine even when CJK
   does not:
   ```python
   from pypdf import PdfReader
   print(PdfReader("IN.pdf").pages[1].extract_text(extraction_mode="layout"))
   ```
3. Write the spec (below), run `make_toc.py`, then `verify_toc.py`.

Cross-check printed page numbers against the physical page: a footer like
`Rev. 0 | Page 12 of 36` means printed 12 == physical 12, i.e. `page_offset: 0`.
When the cover is unnumbered, set `page_offset` instead of hand-adding.

## Workflow B — text layer is garbled (Chinese/Japanese datasheets, scans)

The document still tells you everything; you just have to *look* at it.

```bash
python scripts/probe_pdf.py IN.pdf --render 2 --dpi 200 --outdir _probe
```

1. **Read the TOC page image.** That gives you the real titles and their
   hierarchy (indent = nesting). Do not translate from the English original:
   the Chinese edition routinely renames sections.
2. **Recover the numbers from the text layer** (they are ASCII and survive):
   `extract_text(extraction_mode="layout")` prints one line per TOC row with the
   label garbled but `... 22` intact, in a stable row order. Pair row → page
   number, then label the row with the title you just read.
3. **Locate each heading's `y`** with the font-size scan — chapter headings are
   typically ~17 pt, sections ~11 pt, body 9–10.5 pt:
   ```bash
   python scripts/probe_pdf.py IN.pdf --min-size 16    # chapters only
   python scripts/probe_pdf.py IN.pdf --min-size 11    # + sections (noisier)
   ```
   The printed y is top-origin (`y_top`), which is what the spec wants.
4. Build the spec, build, verify.

Spot-check two or three pages visually before you commit to the outline
(`--render 25,29`). A wrong hierarchy is invisible in a bookmark panel but
obvious in the document.

## The spec

`make_toc.py` and `verify_toc.py` read the same file, so the build is checked
against its own contract:

```json
{
  "title": "AD7606 中文数据手册 Rev.0（含书签目录）",
  "page_offset": 0,
  "page_mode": "UseOutlines",
  "items": [
    {"title": "特性",   "page": 1,  "level": 1, "y": 128.0},
    {"title": "应用",   "page": 1,  "level": 1, "y": 218.0},
    {"title": "技术规格", "page": 4, "level": 1},
    {"title": "时序规格", "page": 7, "level": 2}
  ],
  "toc_page": {
    "page": 2,
    "row_height": 15,
    "columns": [{"x0": 35, "x1": 268}, {"x0": 295, "x1": 556}],
    "rows": [
      {"y": 128.0, "targets": [1, 22]}
    ]
  }
}
```

- `items[].page` — **printed** page number; PDF index = `page - 1 + page_offset`.
  Use `"page_index"` instead when you want to name the PDF index directly.
- `items[].level` — `1` or `2`; a level-2 item becomes a child of the most
  recent level-1 item. Anything deeper gets flattened, so don't plan for it.
- `items[].y` — distance **from the top of the page down to the top of the
  heading line** (exactly `y_top` from `probe_pdf.py`). Omit it and the bookmark
  lands on the page top; supply it and same-page bookmarks stop colliding.
- `toc_page.rows[].y` — same convention, for the printed TOC row; one `targets`
  entry per column, in column order.
- Every target is validated before a byte is written: an out-of-range page is a
  hard error, not a silent no-op bookmark.

## What "clickable printed TOC" buys you

`toc_page` adds `/Link` annotations whose rect spans the whole row (label +
leader dots + page number), so the reader can click anywhere on the line.
`/Border [0 0 0]` and `/F 4` keep them invisible and printable. The bookmark
panel gets a proper nested outline, and `/PageMode /UseOutlines` opens the
document with that panel showing.

## Verify

```bash
python scripts/verify_toc.py IN.pdf OUT.pdf toc.json
```

```
  [PASS] page count unchanged  36 -> 36
  [PASS] bookmark count  expected 30, got 30
  [PASS] bookmark level/title/page in order
  [PASS] opens with the bookmark panel  PageMode=UseOutlines
  [PASS] toc-page link count  expected 30, got 30
  [PASS] toc-page link targets match spec
  [PASS] all 36 pages render identically @72dpi
ALL CHECKS PASSED
```

The pixel comparison is the interesting one: link/bookmark dictionaries must not
change a single visible pixel. If it fails, you changed the content — rebuild
from a fresh clone of the source rather than patching a patched file.

## Files

```
SKILL.md                  this file
scripts/probe_pdf.py      diagnostics + heading scan + page rendering
scripts/make_toc.py       writes the outline and the clickable TOC page
scripts/verify_toc.py     contract + pixel verification
examples/build_demo.py    builds a demo PDF and its spec (no bookmarks → outlined)
examples/demo.pdf         before
examples/demo_outlined.pdf after
references/pitfalls.md    the failure modes, in detail
```

Whole loop, start to finish:

```bash
python examples/build_demo.py
python scripts/make_toc.py examples/demo.pdf examples/demo_toc.json -o examples/demo_outlined.pdf --force
python scripts/verify_toc.py examples/demo.pdf examples/demo_outlined.pdf examples/demo_toc.json
```

## Titles lie

Real case, AD7606 Chinese datasheet (Rev. 0). The English sections are
*Power Dissipation*, *Digital Output*, *Application Hints*. The Chinese edition
says **省电模式** (power-saving mode), **数字滤波器** (digital filter, in the
position the English file uses for digital output), **布局指南** (layout guide).
An outline translated from the English datasheet would have been wrong on three
of thirty entries and nobody would notice until a reader clicked it. Read the
page.
