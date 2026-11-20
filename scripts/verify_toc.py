#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prove the TOC was written correctly — and that nothing else changed.

Three checks, all from the spec that built the file:
  1. bookmarks  : count, order, nesting, title text, target page
  2. toc links  : every clickable row resolves to the page the spec names
  3. pixels     : all pages render identically to the source (annotations
                  must not alter the visible page)

Usage
-----
    python verify_toc.py IN.pdf OUT.pdf toc.json
    python verify_toc.py IN.pdf OUT.pdf toc.json --dpi 100 --no-pixels

Exit codes: 0 = all checks passed, 1 = a check failed, 2 = could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("need PyMuPDF: python -m pip install pymupdf")

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def expected_items(spec: dict) -> list[tuple[int, str, int]]:
    offset = int(spec.get("page_offset", 0))
    out = []
    for it in spec.get("items", []):
        idx = int(it["page_index"]) if "page_index" in it else int(it["page"]) - 1 + offset
        out.append((int(it.get("level", 1)), str(it["title"]).strip(), idx + 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("spec")
    ap.add_argument("--dpi", type=int, default=72)
    ap.add_argument("--no-pixels", action="store_true")
    args = ap.parse_args()

    for path in (args.src, args.dst, args.spec):
        if not os.path.isfile(path):
            sys.exit(f"no such file: {path}")
    with open(args.spec, "r", encoding="utf-8-sig") as fh:
        spec = json.load(fh)

    a = pymupdf.open(args.src)
    b = pymupdf.open(args.dst)
    print(f"source: {os.path.basename(args.src)} ({a.page_count} pages)")
    print(f"output: {os.path.basename(args.dst)} ({b.page_count} pages)")

    check(a.page_count == b.page_count, "page count unchanged",
          f"{a.page_count} -> {b.page_count}")

    # ---------------- 1. bookmarks ----------------
    want = expected_items(spec)
    got = [(lvl, title, page) for lvl, title, page in b.get_toc(simple=True)]
    check(len(got) == len(want), "bookmark count", f"expected {len(want)}, got {len(got)}")
    mismatch = []
    for i, (exp, act) in enumerate(zip(want, got)):
        if exp != act:
            mismatch.append(f"#{i + 1} expected {exp} got {act}")
    check(not mismatch, "bookmark level/title/page in order",
          "" if not mismatch else f"{len(mismatch)} mismatched")
    for line in mismatch[:12]:
        print(f"         - {line}")

    cat = b.pdf_catalog()
    mode = b.xref_get_key(cat, "PageMode")[1].lstrip("/")
    check(mode == "UseOutlines", "opens with the bookmark panel", f"PageMode={mode or 'none'}")

    # ---------------- 2. clickable TOC page ----------------
    toc_page = spec.get("toc_page")
    if toc_page:
        page_idx = int(toc_page["page"]) - 1
        rows = toc_page.get("rows", [])
        offset = int(spec.get("page_offset", 0))
        want_links = []
        for row in rows:
            for target in row.get("targets") or []:
                want_links.append(int(target) - 1 + offset + 1)
        if PdfReader is not None:
            reader = PdfReader(args.dst)
            ref2page = {pg.indirect_reference.idnum: i + 1
                        for i, pg in enumerate(reader.pages)}
            annots = reader.pages[page_idx].get("/Annots") or []
            got_links = []
            for an in annots:
                an = an.get_object()
                dest = an.get("/Dest")
                if not dest:
                    continue
                ref = dest[0]
                got_links.append(ref2page.get(getattr(ref, "idnum", -1), -1))
            check(len(got_links) == len(want_links), "toc-page link count",
                  f"expected {len(want_links)}, got {len(got_links)}")
            check(got_links == want_links, "toc-page link targets match spec",
                  "" if got_links == want_links else "differs")
            if got_links != want_links:
                for i, (w_, g_) in enumerate(zip(want_links, got_links)):
                    if w_ != g_:
                        print(f"         - link #{i + 1}: expected p{w_}, got p{g_}")
        else:
            print("  [SKIP] toc-page links (pypdf not installed)")

    # ---------------- 3. visual integrity ----------------
    if args.no_pixels:
        print("  [SKIP] pixel comparison (--no-pixels)")
    else:
        differing = []
        for i in range(a.page_count):
            pa, pb = a[i].get_pixmap(dpi=args.dpi), b[i].get_pixmap(dpi=args.dpi)
            if (pa.width, pa.height) != (pb.width, pb.height) or pa.samples != pb.samples:
                differing.append(i + 1)
        check(not differing, f"all {a.page_count} pages render identically @{args.dpi}dpi",
              "" if not differing else f"differing pages: {differing[:10]}")

    print()
    if failures:
        print(f"FAILED ({len(failures)} check(s)): " + "; ".join(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
