"""Plain-text renderers: ``raw`` and ``txt``."""

from __future__ import annotations

import re

from ..model import BlockKind, Document


def render_raw(doc: Document) -> str:
    """Every piece of extracted text, page by page, in reading order.

    Nothing is dropped or corrected: running headers/footers, page numbers,
    rotated margin text and low-confidence OCR output are included. Large
    horizontal gaps are kept as tabs; pages are separated by form feeds.
    """
    pages = []
    for page in doc.pages:
        parts = [b.raw_text for b in page.all_blocks if b.raw_text.strip()]
        pages.append("\n\n".join(parts))
    return "\n\f".join(pages).rstrip() + "\n"


def render_txt(doc: Document) -> str:
    """Sanitized running text of the document body."""
    out: list[str] = []
    for b in doc.body_blocks:
        text = b.text.strip()
        if not text:
            continue
        if b.kind is BlockKind.HEADING:
            text = " ".join(text.split())
        out.append(text)
    txt = "\n\n".join(out)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip() + "\n" if txt.strip() else ""
