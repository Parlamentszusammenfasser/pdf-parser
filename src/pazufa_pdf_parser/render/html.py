"""Lightweight structured HTML: headings, paragraphs, columns, synopsis rows."""

from __future__ import annotations

from html import escape

from ..model import Block, BlockKind, Document, Region, RegionKind

CSS = """
:root{color-scheme:light dark}
body{font:16px/1.5 Georgia,'Times New Roman',serif;max-width:60rem;margin:2rem auto;padding:0 1rem}
section.page{position:relative}
section.page+section.page{border-top:1px dashed #8886;margin-top:1.5rem;padding-top:1rem}
.pno{position:absolute;right:0;top:.2rem;font:12px system-ui,sans-serif;opacity:.5}
.cols{display:grid;gap:1.5rem;align-items:start}
.synopsis{display:grid;grid-template-columns:1fr 1fr;gap:.2rem 1.5rem}
p.item{margin-left:1.5rem;text-indent:-1.5rem}
p.footnote{font-size:.85em;opacity:.8}
p{margin:.5rem 0;white-space:pre-line}
h1,h2,h3,h4,h5,h6{line-height:1.25}
"""


def _block_html(b: Block) -> str:
    text = b.text.strip()
    if not text:
        return ""
    labels = f' data-labels="{escape(" ".join(sorted(b.labels)))}"' if b.labels else ""
    if b.kind is BlockKind.HEADING:
        lvl = min(6, b.level + 1)
        return f"<h{lvl}{labels}>{escape(' '.join(text.split()))}</h{lvl}>"
    cls = (
        ' class="item"'
        if b.kind is BlockKind.LIST_ITEM
        else ' class="footnote"'
        if b.kind is BlockKind.FOOTNOTE
        else ""
    )
    return f"<p{cls}{labels}>{escape(text)}</p>"


def _synopsis_rows(region: Region) -> list[tuple[list[Block], list[Block]]]:
    """Align left/right blocks into rows by vertical overlap."""
    left = [(b, 0) for b in region.children[0].iter_blocks()]
    right = [(b, 1) for b in region.children[1].iter_blocks()]
    items = sorted(left + right, key=lambda t: (t[0].bbox.y0, t[1]))
    rows: list[tuple[list[Block], list[Block]]] = []
    bottom = -1e9
    for b, side in items:
        if not rows or b.bbox.y0 >= bottom - 1:
            rows.append(([], []))
            bottom = b.bbox.y1
        rows[-1][side].append(b)
        bottom = max(bottom, b.bbox.y1)
    return rows


def _region_html(r: Region) -> str:
    if r.kind is RegionKind.LEAF:
        return "\n".join(h for b in r.blocks if (h := _block_html(b)))
    if r.kind is RegionKind.COLUMNS and r.synopsis and len(r.children) == 2:
        cells = []
        for lb, rb in _synopsis_rows(r):
            cells.append('<div class="l">' + "\n".join(h for b in lb if (h := _block_html(b))) + "</div>")
            cells.append('<div class="r">' + "\n".join(h for b in rb if (h := _block_html(b))) + "</div>")
        return '<div class="synopsis">\n' + "\n".join(cells) + "\n</div>"
    if r.kind is RegionKind.COLUMNS:
        widths = [max(c.bbox.width, 1.0) for c in r.children]
        total = sum(widths)
        tmpl = " ".join(f"{w / total * 10:.2f}fr" for w in widths)
        inner = "\n".join(f'<div class="col">{_region_html(c)}</div>' for c in r.children)
        return f'<div class="cols" style="grid-template-columns:{tmpl}">\n{inner}\n</div>'
    return "\n".join(h for c in r.children if (h := _region_html(c)))


def render_html(doc: Document) -> str:
    pages = []
    for p in doc.pages:
        body = _region_html(p.layout) if p.layout else ""
        if not body.strip():
            continue
        pages.append(
            f'<section class="page" data-page="{p.number}"><span class="pno">{p.number}</span>\n{body}\n</section>'
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(doc.source or 'Dokument')}</title>\n"
        '<meta name="generator" content="pazufa-parser">\n'
        f"<style>{CSS}</style>\n</head>\n<body>\n<article>\n" + "\n".join(pages) + "\n</article>\n</body>\n</html>\n"
    )
