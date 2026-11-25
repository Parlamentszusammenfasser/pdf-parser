"""Paragraphs split by page and column breaks, joined again after furniture is removed."""

from __future__ import annotations

import re

from .model import Block, BlockKind, Document
from .sanitize import is_line_structured, join_hyphenated

_SENTENCE_END = tuple('.!?:;)“"»…')
_SALUTATION_RE = re.compile(r"^\s*(Sehr geehrte[rs]?|Liebe[rs]?|Hallo|Guten Tag|Dear)\b", re.I)


def merge_flow(doc: Document) -> int:
    """Join paragraphs split by page/column breaks or spurious layout splits.

    Across regions/pages a join requires similar, reasonably wide blocks (never a
    sidebar); inside a region only clear continuations (next block starts lower-case)
    are joined.
    """
    # a synopsis' columns are parallel versions, a ruled table's rows and cells stand alone
    skip = {i for p in doc.pages for i in p.block_ids(lambda r: r.synopsis or r.ruled)}
    widths = {p.number: p.width or 1.0 for p in doc.pages}  # numbers count from the PDF's page 1, not first_page
    prev: Block | None = None
    joins = 0
    for b in doc.body_blocks:
        if not b.text or b.kind is BlockKind.FOOTNOTE:
            continue  # footnotes sit between a page's last and the next page's first paragraph
        if (
            prev is not None
            and id(b) not in skip
            and id(prev) not in skip
            and prev.kind in (BlockKind.PARAGRAPH, BlockKind.LIST_ITEM)
            and b.kind is BlockKind.PARAGRAPH
        ):
            same_region = prev.page == b.page and prev.region == b.region
            page_w = widths[b.page]
            compatible = same_region or (
                min(prev.bbox.width, b.bbox.width) >= 0.35 * page_w
                and min(prev.bbox.width, b.bbox.width) / max(prev.bbox.width, b.bbox.width, 1.0) >= 0.6
            )
            joined = None
            if compatible and not _SALUTATION_RE.match(prev.text):
                if not same_region:
                    joined = join_hyphenated(prev.text, b.text)
                # inside one region only prose continues ("- Kläger -" / "gegen" must stay apart)
                prose = not same_region or (
                    prev.bbox.width >= 0.5 * page_w and not is_line_structured(prev.text.split("\n"))
                )
                if joined is None and prose and not prev.text.rstrip().endswith(_SENTENCE_END) and b.text[:1].islower():
                    joined = prev.text.rstrip() + " " + b.text.lstrip()
            if joined is not None:
                joins += 1
                if prev.page == b.page:
                    prev.text = joined
                    b.text = ""
                    b.labels.add("merged_into_previous")
                    continue
                _continue_on_next_page(prev, b)
                if not b.text:
                    continue
        prev = b
    return joins


def _continue_on_next_page(prev: Block, b: Block) -> None:
    """Each page keeps its own text, so page citations stay right: ``prev`` is marked to continue on ``b``'s page,
    and a word divided at the page break ("Ände-" / "rung") goes whole to the page it starts on."""
    word, *rest = b.text.split(maxsplit=1)
    whole = join_hyphenated(prev.text, word)
    if whole is not None and whole != prev.text.rstrip() + " " + word:  # not "Aus-" / "und Fortbildung"
        prev.text = whole
        b.text = rest[0] if rest else ""
    prev.continues_on = b.page if b.text else None
