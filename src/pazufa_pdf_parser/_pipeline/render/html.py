"""Lightweight structured HTML: headings, paragraphs, list items and footnotes in reading order."""

from __future__ import annotations

from html import escape

from ...document import Block, BlockKind, PdfDocument

CSS = """
:root{color-scheme:light dark}
body{font:16px/1.5 Georgia,'Times New Roman',serif;max-width:60rem;margin:2rem auto;padding:0 1rem}
section.page{position:relative}
section.page+section.page{border-top:1px dashed #8886;margin-top:1.5rem;padding-top:1rem}
.pno{position:absolute;right:0;top:.2rem;font:12px system-ui,sans-serif;opacity:.5}
p.item{margin-left:1.5rem;text-indent:-1.5rem}
p.footnote{font-size:.85em;opacity:.8}
p{margin:.5rem 0;white-space:pre-line}
h1,h2,h3,h4,h5,h6{line-height:1.25}
"""

_CLASS = {BlockKind.LIST_ITEM: ' class="item"', BlockKind.FOOTNOTE: ' class="footnote"'}


def _block_html(b: Block) -> str:
    if b.kind is BlockKind.HEADING:
        level = min(6, b.level + 1)
        return f"<h{level}>{escape(b.text)}</h{level}>"
    return f"<p{_CLASS.get(b.kind, '')}>{escape(b.text)}</p>"


def render_html(doc: PdfDocument) -> str:
    pages = []
    for p in doc.pages:
        body = "\n".join(_block_html(b) for b in p.blocks if b.kind.is_body and b.text)
        if body:
            pages.append(
                f'<section class="page" data-page="{p.number}"><span class="pno">{p.number}</span>\n{body}\n</section>'
            )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(doc.metadata.title or 'Dokument')}</title>\n"
        '<meta name="generator" content="pazufa-parser">\n'
        f"<style>{CSS}</style>\n</head>\n<body>\n<article>\n" + "\n".join(pages) + "\n</article>\n</body>\n</html>\n"
    )
