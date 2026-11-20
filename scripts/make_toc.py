#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write a table of contents (bookmarks) into a PDF, and optionally turn the
document's own printed TOC page into clickable links.

Input is a JSON spec so the same file drives building *and* verification:

    python make_toc.py IN.pdf toc.json -o OUT.pdf
    python make_toc.py IN.pdf toc.json -o OUT.pdf --force

Spec
----
{
  "title": "Document title written to metadata (optional)",
  "subject": "...", "author": "...",                       // optional
  "page_offset": 0,          // PDF index = printed page - 1 + page_offset
  "page_mode": "UseOutlines",// open with the bookmark panel visible (default)
  "default_y": null,         // fallback y_top when an item has none
  "items": [
    {"title": "概述", "page": 3, "level": 1, "y": 83.3},
    {"title": "时序规格", "page": 7, "level": 2},
    { "title": "...", "page": 3, "level": 2, "page_index": 2 }   // explicit index wins
  ],
  "toc_page": {                    // optional: make the printed TOC clickable
    "page": 2,
    "row_height": 13,              // clickable band height in pt
    "columns": [{"x0": 35, "x1": 268}, {"x0": 295, "x1": 556}],
    "rows": [{"y": 133.0, "targets": [1, 22]}, ...]
  }
}

`y` is always measured **from the top edge of the page down to the top of the
target line** (the `y_top` that probe_pdf.py prints). That is the intuitive
direction; the conversion into PDF's bottom-origin /XYZ destination happens here.

Every page number is validated against the document, and nothing is written if
any target is out of range.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject,
    )
except ImportError:  # pragma: no cover
    sys.exit("need pypdf: python -m pip install pypdf")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOP_PAD = 8.0  # put the heading this far below the viewport top


def load_spec(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def resolve_index(item: dict, offset: int) -> int:
    if "page_index" in item:
        return int(item["page_index"])
    if "page" not in item:
        raise ValueError(f"item without page/page_index: {item.get('title')!r}")
    return int(item["page"]) - 1 + offset


def make_link(page_refs, dst_idx, rect, top):
    dest = ArrayObject([
        page_refs[dst_idx],
        NameObject("/XYZ"),
        FloatObject(0),
        FloatObject(top),
        FloatObject(0),
    ])
    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
        NameObject("/Border"): ArrayObject(
            [FloatObject(0), FloatObject(0), FloatObject(0)]),
        NameObject("/F"): FloatObject(4),  # printable, no border drawn
        NameObject("/Dest"): dest,
    })
    return annot


def main() -> int:
    ap = argparse.ArgumentParser(description="Add bookmarks / clickable TOC to a PDF.")
    ap.add_argument("pdf")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--force", action="store_true", help="overwrite the output file")
    args = ap.parse_args()

    src, dst = os.path.abspath(args.pdf), os.path.abspath(args.out)
    if src == dst:
        sys.exit("refusing to write over the source file; pick another -o path")
    if os.path.exists(dst) and not args.force:
        sys.exit(f"output exists: {dst}  (use --force)")
    if not os.path.isfile(src):
        sys.exit(f"no such file: {src}")

    spec = load_spec(args.spec)
    items = spec.get("items") or []
    if not items:
        sys.exit("spec has no items")
    offset = int(spec.get("page_offset", 0))

    w = PdfWriter(clone_from=src)
    npages = len(w.pages)
    page_refs = [p.indirect_reference for p in w.pages]
    page_h = float(w.pages[0].mediabox.height)
    default_y = spec.get("default_y")

    # ---- validate everything before touching the file ----
    problems, resolved = [], []
    for it in items:
        title = str(it.get("title", "")).strip()
        if not title:
            problems.append("item with empty title")
            continue
        level = int(it.get("level", 1))
        if level not in (1, 2):
            problems.append(f"{title!r}: level must be 1 or 2")
        try:
            idx = resolve_index(it, offset)
        except Exception as exc:
            problems.append(f"{title!r}: {exc}")
            continue
        if not 0 <= idx < npages:
            problems.append(f"{title!r}: page resolves to {idx + 1}, document has {npages}")
        y = it.get("y", default_y)
        resolved.append((title, idx, level, y))
    if problems:
        print("spec rejected:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 2

    # ---- bookmarks ----
    chapter = None
    for title, idx, level, y in resolved:
        parent = None if level == 1 else chapter
        if level == 2 and chapter is None:
            print(f"warning: {title!r} is level 2 but no level 1 came before it;"
                  " promoting to level 1", file=sys.stderr)
            parent = None
        node = w.add_outline_item(
            title=TextStringObject(title), page_number=idx, parent=parent)
        if not isinstance(node, DictionaryObject):  # pypdf hands back an IndirectObject
            node = node.get_object()
        target_top = page_h if y is None else min(page_h, page_h - float(y) + TOP_PAD)
        node[NameObject("/Dest")] = ArrayObject([
            page_refs[idx], NameObject("/XYZ"),
            FloatObject(0), FloatObject(target_top), FloatObject(0)])
        if parent is None:
            chapter = node

    # ---- clickable printed TOC page ----
    toc_page = spec.get("toc_page")
    links_added = 0
    if toc_page:
        page_idx = int(toc_page["page"]) - 1
        if not 0 <= page_idx < npages:
            sys.exit(f"toc_page {toc_page['page']} out of range")
        row_h = float(toc_page.get("row_height", 13))
        columns = toc_page.get("columns") or []
        if not columns:
            sys.exit("toc_page needs at least one column {x0,x1}")
        page = w.pages[page_idx]
        annots = page.get("/Annots")
        if annots is None:
            annots = ArrayObject()
            page[NameObject("/Annots")] = annots
        for row in toc_page.get("rows", []):
            y_top = float(row["y"])
            targets = row.get("targets") or []
            rect_y0 = page_h - (y_top + row_h)
            rect_y1 = page_h - y_top
            for col, target in zip(columns, targets):
                t_idx = int(target) - 1 + offset
                if not 0 <= t_idx < npages:
                    print(f"warning: toc row y={y_top} target {target} out of range;"
                          " skipped", file=sys.stderr)
                    continue
                annots.append(make_link(
                    page_refs, t_idx,
                    (float(col["x0"]), rect_y0, float(col["x1"]), rect_y1),
                    page_h))
                links_added += 1

    # ---- document level settings ----
    page_mode = spec.get("page_mode", "UseOutlines")
    if page_mode:
        w.page_mode = "/" + str(page_mode).lstrip("/")

    meta = {}
    for key, pk in (("title", "/Title"), ("subject", "/Subject"), ("author", "/Author")):
        if spec.get(key):
            meta[pk] = spec[key]
    if meta:
        w.add_metadata(meta)

    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        w.write(fh)
    os.replace(tmp, dst)

    print(f"wrote {dst}")
    print(f"  pages          : {npages}")
    print(f"  bookmarks      : {len(resolved)}")
    print(f"  toc-page links : {links_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
