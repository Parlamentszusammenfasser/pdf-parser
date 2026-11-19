"""Plain-text renderers: ``raw`` and ``txt``."""

from __future__ import annotations

from ..._document import PdfDocument


def render_raw(doc: PdfDocument) -> str:
    """Every block, page by page, in reading order, including what ``txt`` leaves out.

    Running headers, footers, page numbers, rotated margin notes and OCR noise
    are kept. The text of each block is sanitized like in ``txt`` (de-hyphenated,
    paragraphs re-joined); pages are separated by form feeds.
    """
    pages = ["\n\n".join(b.text for b in page.blocks if b.text) for page in doc.pages]
    return "\n\f".join(pages).rstrip() + "\n"


def render_txt(doc: PdfDocument) -> str:
    """Sanitized running text of the document body."""
    txt = doc.text()
    return txt + "\n" if txt else ""
