# Failure modes, measured

Everything here comes from a real run: a 36-page Chinese AD7606 datasheet made by
Adobe Illustrator CS4, 2010. Numbers are from that file.

## 1. Why the text layer is garbage

All 5 Chinese faces look like this:

```
/HYb2gj-GBK-EUC-H-Identity-H   /Type0   Encoding /Identity-H   no /ToUnicode
```

Consequences, in order of how much time they cost people:

- `/ToUnicode` count in the raw file: **0**.
- No `/ActualText`, no `/StructTreeRoot` — there is no second channel to escape through.
- `/Identity-H` means the 2-byte codes in the content stream are treated as CIDs.
  Those CIDs are the *subset font's glyph indices*.
- Every extractor (pypdf, PyMuPDF, Acrobat copy-paste, `pdftotext`) therefore emits
  `chr(glyph_id)`. Glyph 4043 happens to be a Tibetan letter, so the "text" comes
  out as `Ϫ۩૦๏` / `ཚڢ` / `ገ࣑`.

Measured: 24.1 % of extracted code points fall in Tibetan / Arabic / Armenian /
Thai / Ethiopic / Myanmar blocks, and 0 % in CJK Unified Ideographs. That is the
signature `probe_pdf.py` reports as `garbled`.

**Do not build a CID→character table.** Two glyph IDs for 数 exist in the same
file, because the document embeds separate subset fonts for body, bold and
heading styles:

| char | in one font | in another font (same page) |
|---|---|---|
| 数 (part of 数字接口) | `ຕ` | `ገ` |
| 换 (part of 转换控制) | `࣑` | — |

Any substitution table you derive from one phrase will silently corrupt the next
one. Rendering the page and reading it takes one command.

## 2. Character counts lie too

`pypdf`'s visitor reports text-matrix positions, but a heading is frequently
emitted as several fragments — `ገ`, `࣑`, `੦዆!` — and neighbouring fragments can
merge (`ఇ५!` was 2 chars + a bullet, `ຕጴ୳հഗ!` was 5 chars + a bullet). Counting
characters in an extracted string to guess the title length is a dead end; it
convinced me that a section called 功耗 was at page 25 when the document says
省电模式.

## 3. Numbers survive — use them

On the same TOC page, with every label garbled, `extract_text(extraction_mode="layout")`
still prints:

```
༬Ⴀ                                     1      ! ఇె๼෇                                      22
ᆌᆩ                                     1       ADCدڿࡧຕ                                    23
```

Two columns, 15 rows each, page numbers intact and monotonic. Pair row → number
mechanically, then attach the titles you read off the rendered image. This is the
whole trick for garbled documents: **numbers from the text layer, words from the
pixels.**

## 4. pypdf outline API gotchas (7.x)

```python
node = writer.add_outline_item(title=TextStringObject(t), page_number=idx, parent=None)
```

- Keyword arguments only — positional args raise a `DeprecationWarning` in 7.x and
  are removed in 8.0.
- It returns an **`IndirectObject`**, not a dict. `node["/Dest"] = ...` raises
  `TypeError: 'IndirectObject' object does not support item assignment`; call
  `node.get_object()` first.
- There is no `y`/`top` parameter. Landing at page top is not enough when several
  bookmarks share a page (3 chapters on page 1, 4 sections on page 27), so patch
  the destination afterwards:

  ```python
  node[NameObject("/Dest")] = ArrayObject([
      page_refs[idx], NameObject("/XYZ"),
      FloatObject(0), FloatObject(top_from_bottom), FloatObject(0)])
  ```

- Nesting = pass the **level-1 node** as `parent`. Track it in a variable; don't
  pass the level-2 node by mistake or you get a 3-deep tree.

## 5. Two coordinate systems, one sign flip

- PDF `/XYZ` destination: `[page, /XYZ, left, TOP, zoom]`, **bottom-origin**. `TOP`
  is the y of the viewport's top edge, so a heading whose baseline sits at 647 pt
  on a 792 pt page wants `TOP ≈ 659`.
- PyMuPDF: `page.get_text("dict")` bboxes and `get_toc()[i].y` are **top-origin**
  (distance from the top). The same destination reads as `133` there.
- So: spec stores top-origin `y` (human-intuitive, matches the probe), and
  `make_toc.py` converts with `TOP = page_height - y + 8`. Verify numerically —
  if `verify_toc.py` reports pages but you see the wrong scroll position, you
  flipped the sign, not the page number.

## 6. Link annotations that don't look like annotations

```python
NameObject("/Border"): ArrayObject([0, 0, 0])   # no border box
NameObject("/F"): FloatObject(4)                # printable, so it won't vanish in print
```

Span the rect across the leader dots and the page number (`x0` of the label to
`x1` of the number); clicking 5 mm right of a title is what users actually do.

## 7. Verification must be pixel-level

Adding annotations is supposed to be content-neutral, so:

```python
a[i].get_pixmap(dpi=72).samples == b[i].get_pixmap(dpi=72).samples
```

36/36 pages identical on the reference file. If one page differs, something
re-rendered it — and the fix is to rebuild from the pristine source, never to
patch the patched output.

## 8. Windows / plumbing

- `sys.stdout.reconfigure(encoding="utf-8")` or Chinese titles print as `?`.
- Read JSON specs with `encoding="utf-8-sig"`: Notepad and PowerShell love a BOM,
  and `json.load` fails on it.
- Filenames with Chinese characters are fine, but keep the output next to the
  source and never `os.replace()` onto the input.
- `Select-Object -First N` in PowerShell closes the pipe early, so a Python
  script may exit 1 with a `BrokenPipeError` — that is the pipe, not the PDF.
- PyMuPDF is AGPL, which is why this skill is AGPL as well.

## 9. Where a translated document deviates

Do not assume the translation follows the English structure. On the reference
file, three of thirty section names were different, and one section sat at a
different position in the order. Reading the rendered TOC page is not optional
politeness — it is the only source of truth.
