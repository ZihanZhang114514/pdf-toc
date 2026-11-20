#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a small self-contained demo PDF (with a printed TOC page and *no*
bookmarks) plus the JSON spec that turns it into an outlined document.

    python examples/build_demo.py
    # -> examples/demo.pdf, examples/demo_toc.json

The spec is derived from the rendered PDF itself (line bboxes), not from the
coordinates used to draw it, so it exercises the same numbers probe_pdf.py
reports. Then:

    python scripts/probe_pdf.py examples/demo.pdf
    python scripts/make_toc.py examples/demo.pdf examples/demo_toc.json \
        -o examples/demo_outlined.pdf --force
    python scripts/verify_toc.py examples/demo.pdf examples/demo_outlined.pdf \
        examples/demo_toc.json
"""
from __future__ import annotations

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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, "demo.pdf")
SPEC = os.path.join(HERE, "demo_toc.json")

PAGE_W, PAGE_H = 595, 842  # A4
LEFT = 72.0
BODY_SIZE = 10.5
H1, H2 = 18.0, 12.5

CJK_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]

LATIN = ("This is a demo document. Its printed table of contents looks fine, "
         "but the PDF itself has no bookmarks at all - that is the gap this "
         "skill fills. Nothing here is real engineering content.")

# (level, title) per page; level 0 = not in the outline
PAGES: list[list[tuple[int, str]]] = [
    [(1, "特性"),
     (1, "应用")],
    [],                                    # the printed TOC page
    [(1, "概述")],
    [(1, "技术规格"),
     (2, "时序规格")],
    [(1, "工作原理")],
    [(2, "模拟输入"),
     (1, "数字接口")],
    [(2, "并行接口"),
     (1, "附录 A")],
    [(1, "结束语")],
]

# printed TOC: (left title, left page, right title, right page)
TOC_ROWS = [
    ("特性", 1, "工作原理", 5),
    ("应用", 1, "模拟输入", 6),
    ("概述", 3, "数字接口", 6),
    ("技术规格", 4, "并行接口", 7),
    ("时序规格", 4, "附录 A", 7),
]


def find_cjk_font() -> str | None:
    for path in CJK_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def draw(page, fontfile, x, y, text, size, color=(0, 0, 0)):
    if fontfile:
        page.insert_text((x, y), text, fontsize=size, color=color,
                         fontfile=fontfile, fontname="cjk")
    else:
        page.insert_text((x, y), text, fontsize=size, color=color,
                         fontname="helv")


def norm(text: str) -> str:
    """Normalise extracted text: PyMuPDF reports the space glyph as U+00A0 here."""
    return " ".join(text.replace("\u00a0", " ").split())


def main() -> int:
    font = find_cjk_font()
    doc = pymupdf.open()
    baselines: dict[str, tuple[int, float]] = {}

    # ---- page 1: cover ----
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    draw(page, font, LEFT, 90, "PDF 目录演示文档", 26)
    draw(page, font, LEFT, 118, "PDF Outline Demo", 16, (0.35, 0.35, 0.35))
    y = 170.0
    for level, title in PAGES[0]:
        draw(page, font, LEFT, y, title, H1)
        baselines[title] = (1, y)
        y += 30
        draw(page, font, LEFT, y, LATIN[:110], BODY_SIZE, (0.2, 0.2, 0.2))
        y += 44
    draw(page, font, LEFT, 800, "第 1 页 / page 1", 9, (0.5, 0.5, 0.5))

    # ---- page 2: printed table of contents ----
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    draw(page, font, LEFT, 90, "目录  Contents", 22)
    y = 140.0
    for lt, lp, rt, rp in TOC_ROWS:
        draw(page, font, LEFT + 10, y, lt, 11)
        draw(page, font, 300 - 10, y, str(lp), 11)
        draw(page, font, 350, y, rt, 11)
        draw(page, font, PAGE_W - LEFT - 10, y, str(rp), 11)
        baselines["_toc_" + lt] = (2, y)
        y += 26
    draw(page, font, LEFT, 800, "第 2 页 / page 2", 9, (0.5, 0.5, 0.5))

    # ---- remaining pages ----
    for pno, entries in enumerate(PAGES[2:], start=3):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 96.0
        for level, title in entries:
            draw(page, font, LEFT, y, title, H1 if level == 1 else H2)
            baselines[title] = (pno, y)
            y += 34 if level == 1 else 28
            draw(page, font, LEFT, y, LATIN[:92], BODY_SIZE, (0.2, 0.2, 0.2))
            y += 40
        # some filler so pages look like pages
        for i in range(6):
            draw(page, font, LEFT, y, LATIN[(i * 13) % 40:][:88], 9.5, (0.4, 0.4, 0.4))
            y += 16
        draw(page, font, LEFT, 800, f"第 {pno} 页 / page {pno}", 9, (0.5, 0.5, 0.5))

    # Subset the CJK font: without this the whole 12 MB face is embedded twice
    # and the demo dwarfs the skill it demonstrates.
    try:
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(PDF, garbage=4, deflate=True, clean=True)
    doc.close()
    print(f"wrote {PDF}")

    # ---- derive the spec from the real PDF ----
    src = pymupdf.open(PDF)
    want: dict[str, list[tuple[int, float]]] = {}
    for pno in range(src.page_count):
        for block in src[pno].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                text = norm("".join(s["text"] for s in line["spans"]))
                if text:
                    want.setdefault(text, []).append((pno + 1, round(line["bbox"][1], 1)))

    items = []
    for pno, entries in enumerate(PAGES, start=1):
        for level, title in entries:
            hits = [h for h in want.get(norm(title), []) if h[0] == pno]
            if not hits:
                sys.exit(f"could not locate heading {title!r} on page {pno}")
            items.append({"title": title, "page": pno, "level": level, "y": hits[0][1]})

    rows = []
    for lt, lp, rt, rp in TOC_ROWS:
        y_left = [h for h in want.get(norm(lt), []) if h[0] == 2][0][1]
        y_right = [h for h in want.get(norm(rt), []) if h[0] == 2][0][1]
        if abs(y_left - y_right) > 1.0:
            sys.exit(f"toc row misaligned: {lt!r} vs {rt!r}")
        rows.append({"y": min(y_left, y_right), "targets": [lp, rp]})

    spec = {
        "title": "PDF 目录演示文档 / PDF Outline Demo",
        "subject": "demo for the pdf-toc skill",
        "page_offset": 0,
        "items": items,
        "toc_page": {
            "page": 2,
            "row_height": 15,
            "columns": [{"x0": 70, "x1": 300}, {"x0": 340, "x1": 525}],
            "rows": rows,
        },
    }
    with open(SPEC, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    print(f"wrote {SPEC}  ({len(items)} bookmarks, {len(rows)} clickable rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
