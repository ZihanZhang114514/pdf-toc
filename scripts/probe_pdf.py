#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconnaissance for a PDF before you write a table of contents for it.

Answers three questions:
  1. Is there an outline (bookmarks) already?
  2. Is the text layer usable, or will extraction come back as mojibake
     (glyph IDs from a subset font that carries no /ToUnicode)?
  3. Where are the headings? (font size + y position, per page)

Usage
-----
    python probe_pdf.py IN.pdf
    python probe_pdf.py IN.pdf --min-size 11 --render 2,25,29 --dpi 200 --outdir ./_probe
    python probe_pdf.py IN.pdf --json > probe.json

`--render` writes page images. If the text layer is garbled, those images are the
only ground truth for section titles: look at them.

Exit codes: 0 ok, 2 cannot open the file.
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
    PdfReader = None  # font/ToUnicode inspection is optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Unicode ranges a *correct* extractor never produces for Chinese/English text.
# Seeing these means the codepoints are font glyph IDs, not characters.
EXOTIC = (
    (0x0530, 0x058F), (0x05D0, 0x05EA), (0x0620, 0x064A), (0x0700, 0x074F),
    (0x0780, 0x07BF), (0x0800, 0x083E), (0x0900, 0x097F), (0x0980, 0x09FF),
    (0x0A80, 0x0AFF), (0x0B80, 0x0BFF), (0x0C00, 0x0C7F), (0x0C80, 0x0CFF),
    (0x0D00, 0x0D7F), (0x0D80, 0x0DFF), (0x0E00, 0x0E7F), (0x0E80, 0x0EFF),
    (0x0F00, 0x0FFF), (0x1000, 0x109F), (0x10A0, 0x10FF), (0x1100, 0x11FF),
    (0x1200, 0x139F), (0x13A0, 0x13FF), (0x1780, 0x17FF), (0x1800, 0x18AF),
)


def is_exotic(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in EXOTIC)


def text_health(text: str) -> dict:
    cjk = ascii_cnt = exotic = total = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            cjk += 1
        elif o < 0x0180:
            ascii_cnt += 1
        elif is_exotic(ch):
            exotic += 1
    real = cjk + ascii_cnt
    verdict = "ok"
    if total and exotic / total > 0.15:
        verdict = "garbled"
    elif total and real == 0:
        verdict = "no-readable-text"
    return {"cjk": cjk, "latin": ascii_cnt, "exotic": exotic,
            "total": total, "verdict": verdict}


def font_inventory(path: str) -> list[dict]:
    """BaseFont / subtype / ToUnicode presence, deduplicated."""
    if PdfReader is None:
        return []
    try:
        reader = PdfReader(path)
    except Exception:
        return []
    seen: dict[str, dict] = {}
    for page in reader.pages:
        try:
            fonts = page.get("/Resources", {}).get("/Font", {})
        except Exception:
            continue
        if not hasattr(fonts, "get_object"):
            continue
        fonts = fonts.get_object()
        for _name, ref in fonts.items():
            try:
                f = ref.get_object()
            except Exception:
                continue
            base = str(f.get("/BaseFont", "?"))
            if base in seen:
                continue
            enc = f.get("/Encoding")
            seen[base] = {
                "basefont": base,
                "subtype": str(f.get("/Subtype", "?")),
                "encoding": str(enc) if enc is not None else None,
                "identity_h": "Identity" in str(enc),
                "to_unicode": "/ToUnicode" in f,
                "has_cmap_name": "-GBK-" in base or "-EUC-" in base,
            }
    return list(seen.values())


def headings(doc, min_size: float) -> list[dict]:
    out = []
    for pno in range(doc.page_count):
        page = doc[pno]
        try:
            data = page.get_text("dict")
        except Exception:
            continue
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                size = max(round(s["size"], 1) for s in spans)
                if size < min_size:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                out.append({
                    "page": pno + 1,
                    "size": size,
                    "y_top": round(line["bbox"][1], 1),
                    "text": text,
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe a PDF before building its TOC.")
    ap.add_argument("pdf")
    ap.add_argument("--min-size", type=float, default=11.0,
                    help="minimum font size treated as a heading (default 11.0; "
                         "body text is usually 9-10.5pt)")
    ap.add_argument("--render", default="",
                    help="comma separated page numbers to render as PNG")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--outdir", default="_probe")
    ap.add_argument("--json", action="store_true", help="machine readable report")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        sys.exit(f"no such file: {args.pdf}")
    try:
        doc = pymupdf.open(args.pdf)
    except Exception as exc:
        sys.exit(f"cannot open: {exc}")

    outline = doc.get_toc(simple=False)
    fonts = font_inventory(args.pdf)
    page_health = []
    for pno in range(doc.page_count):
        h = text_health(doc[pno].get_text())
        h["page"] = pno + 1
        page_health.append(h)

    total_chars = sum(h["total"] for h in page_health)
    exotic_chars = sum(h["exotic"] for h in page_health)
    garbled_pages = [h["page"] for h in page_health if h["verdict"] == "garbled"]
    identity_no_tounicode = [f["basefont"] for f in fonts
                             if f["identity_h"] and not f["to_unicode"]]

    report = {
        "file": os.path.abspath(args.pdf),
        "pages": doc.page_count,
        "page_size": [round(doc[0].rect.width, 1), round(doc[0].rect.height, 1)],
        "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
        "outline_entries": len(outline),
        "text_layer": {
            "chars": total_chars,
            "exotic_ratio": round(exotic_chars / total_chars, 3) if total_chars else 0,
            "garbled_pages": garbled_pages,
            "verdict": "garbled" if garbled_pages else (
                "empty" if total_chars == 0 else "ok"),
        },
        "fonts": fonts,
        "fonts_identity_h_without_tounicode": identity_no_tounicode,
        "headings": headings(doc, args.min_size),
    }

    # ---- render pages for visual reading ----
    if args.render:
        os.makedirs(args.outdir, exist_ok=True)
        rendered = []
        for token in args.render.split(","):
            token = token.strip()
            if not token:
                continue
            pno = int(token)
            if not 1 <= pno <= doc.page_count:
                print(f"skip page {pno} (out of range)", file=sys.stderr)
                continue
            out = os.path.join(args.outdir, f"page{pno:03d}.png")
            doc[pno - 1].get_pixmap(dpi=args.dpi).save(out)
            rendered.append(out)
        report["rendered"] = rendered

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"file      : {report['file']}")
    print(f"pages     : {report['pages']}   size: {report['page_size'][0]}x{report['page_size'][1]} pt")
    print(f"title     : {report['metadata'].get('title', '-')}")
    print(f"outline   : {len(outline)} entries" + ("" if outline else "   <-- empty, this is what we add"))
    tl = report["text_layer"]
    print(f"text layer: {tl['verdict']}  ({tl['chars']} chars, exotic {tl['exotic_ratio'] * 100:.1f}%)")
    if tl["garbled_pages"]:
        shown = tl["garbled_pages"][:10]
        print(f"            garbled pages: {shown}{' ...' if len(tl['garbled_pages']) > 10 else ''}")
    if identity_no_tounicode:
        print("fonts     : Identity-H without /ToUnicode ->")
        for name in identity_no_tounicode:
            print(f"            {name}")
    if fonts:
        print("font list :")
        for f in fonts:
            flags = []
            if f["identity_h"]:
                flags.append("Identity-H")
            flags.append("ToUnicode" if f["to_unicode"] else "NO-ToUnicode")
            print(f"            {f['basefont'][:52]:54s} {f['subtype']:8s} {' '.join(flags)}")
    if report["headings"]:
        print(f"\nheading candidates (font size >= {args.min_size}):")
        for h in report["headings"]:
            print(f"  p{h['page']:>3}  y={h['y_top']:6.1f}  {h['size']:>4}pt  {h['text'][:70]}")
    if args.render and report.get("rendered"):
        print("\nrendered:")
        for p in report["rendered"]:
            print(f"  {p}   <-- open this and read the real titles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
