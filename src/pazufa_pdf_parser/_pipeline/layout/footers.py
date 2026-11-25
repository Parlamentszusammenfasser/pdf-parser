"""Second-pass footer detection.

``layout.furniture`` finds running headers/footers by exact-ish repetition. That
misses footers which

* appear on one page only (letters: company data on page 1, last page logos),
* belong to single-page documents (nothing to compare with),
* vary between pages because of OCR (logos read differently every time).

This pass looks at the *bottom zone* of every page: blocks below a clear
vertical gap that ends the body. Each block in the zone is scored on

* font size clearly below the document body size,
* footer vocabulary (register court, board, bank details, contact data, ...),
* OCR noise (logos read as symbol soup),
* OCR-tolerant repetition (token containment) with other pages' bottom zones,
* the size of the gap separating it from the body,
* this page's number printed inside the zone.

Blocks scoring above :data:`THRESHOLD` become ``FOOTER`` furniture (still in
``raw`` output). Numbered notes become ``FOOTNOTE`` blocks, which stay content.
Text that simply continues to the page bottom never forms a zone because no gap
separates it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Block, BlockKind, Document, Page, Region, RegionKind
from .furniture import is_page_number

ZONE_TOP = 0.72  # a footer zone must start below this fraction of the page height
THRESHOLD = 2.5
NUMBERED_ZONE_BONUS = 1.0  # the page number marks the zone as the page footer

_LEXICON = [
    re.compile(p, re.I)
    for p in (
        r"\b(Registergericht|Amtsgericht\s+\w+\s+(HRB|HRA|VR)|HRB\s*\d|HRA\s*\d|VR\s*\d|Vereinsregister|Handelsregister)",
        r"\b(USt-?Id|Umsatzsteuer|Steuer-?Nr|Steuernummer)",
        r"\b(Geschäftsführ\w*|Vorstand|Landesvorstand|Vorsitzende[r]?|Präsident(in)?|Aufsichtsrat)\b",
        r"\b(Bankverbindung|IBAN|BIC|Sparkasse|Bank\b)",
        r"\b(Telefon|Tel\.|Telefax|Fax)\b|\+49\s?\d",
        r"www\.|https?://|@[\w-]+\.\w",
        r"\b(Sitz|Postanschrift|Hausanschrift|Besucheranschrift|Postfach)\b",
        r"\b(abrufbar|Datenschutz|Impressum)\b",
    )
]
_SEPARATORS_RE = re.compile(r"[·•|]| - (?=\S)")
_FOOTNOTE_RE = re.compile(r"^\s*(\d{1,3}|\*{1,3})\)?\s+\S")
_CONTINUATION_RE = re.compile(r"^\s*(?!www\.)[a-zäöüß]+\b(?![.@:/])")
_TOKEN_RE = re.compile(r"[^\W_]{3,}")


@dataclass
class _Zone:
    blocks: list[Block]
    gap: float  # whitespace between the body and the zone


def _tokens(text: str) -> set[str]:
    return {re.sub(r"\d", "#", t.lower()) for t in _TOKEN_RE.findall(text)}


def _bottom_zone(page: Page, sep: float, skip: set[int]) -> _Zone | None:
    blocks = [b for b in page.blocks if b.raw_text.strip() and id(b) not in skip]
    if not blocks:
        return None
    blocks.sort(key=lambda b: b.bbox.y0)
    zone = [blocks[-1]]
    top = blocks[-1].bbox.y0
    gap = None
    for b in reversed(blocks[:-1]):
        g = top - b.bbox.y1
        if g >= sep:
            gap = g
            break
        zone.append(b)
        top = min(top, b.bbox.y0)
    if gap is None or top < page.height * ZONE_TOP:
        return None  # body runs down to the bottom, or the zone is too large to be a footer
    return _Zone(zone, gap)


def lexicon_hits(text: str) -> int:
    return sum(1 for rx in _LEXICON if rx.search(text))


def looks_like_logo(block: Block) -> bool:
    """Few letters or low OCR confidence, as logos read as text are: a hint for a footer, not proof of noise."""
    text = block.raw_text.replace(" ", "").replace("\n", "")
    if not text:
        return True
    alnum = sum(c.isalnum() for c in text) / len(text)
    conf = block.confidence
    return alnum < 0.7 or (conf is not None and conf < 60)


def zone_page_number(blocks: list[Block], page: int) -> Block | None:
    """The block holding this page's number: alone, or closing a text line after a tab (BW Drucksachen
    close page 1's "Ausgegeben: …" footer row with it). Several numbered lines are a table."""
    rows = [(b, ln.text.split("\t")) for b in blocks for ln in b.lines]
    numbered = [(b, cells) for b, cells in rows if _number(cells[-1]) is not None]
    if len(numbered) != 1:
        return None
    b, [*text, last] = numbered[0]
    lone = len(b.lines) == 1 and not text
    return b if _number(last) == page and (lone or _has_letters(text)) else None


def _number(text: str) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group()) if m and is_page_number(text) else None


def _has_letters(cells: list[str]) -> bool:
    return any(c.isalpha() for cell in cells for c in cell)


def footer_score(block: Block, body_size: float, gap: float, repeated: bool, numbered_zone: bool = False) -> float:
    text = block.raw_text
    score = NUMBERED_ZONE_BONUS if numbered_zone else 0.0
    if block.size and block.size < 0.88 * body_size:
        score += 2.0
    hits = lexicon_hits(text)
    score += min(1.5, 0.75 * hits)
    if len(_SEPARATORS_RE.findall(text)) >= 2:
        score += 0.75
    if looks_like_logo(block):
        score += 1.5
    if repeated:
        score += 2.0
    if gap >= 3 * body_size:
        score += 0.5
    if _CONTINUATION_RE.match(text):
        score -= 2.0  # continues a sentence
    return score


def is_footnote(block: Block, body_size: float) -> bool:
    text = block.raw_text
    return bool(_FOOTNOTE_RE.match(text)) and block.size < 0.95 * body_size and lexicon_hits(text) == 0


def _detach(region: Region, block: Block) -> bool:
    if region.kind is RegionKind.LEAF:
        for i, b in enumerate(region.blocks):
            if b is block:
                del region.blocks[i]
                return True
        return False
    return any(_detach(c, block) for c in region.children)


def refine_footers(doc: Document) -> int:
    """Move footer blocks of the bottom zones into page furniture. Returns the count."""
    body_size = doc.body_size
    sep = max(1.8 * body_size, 14.0)
    zones: dict[int, _Zone] = {}
    for i, page in enumerate(doc.pages):
        z = _bottom_zone(page, sep, page.block_ids(lambda r: r.synopsis))
        if z is not None:
            zones[i] = z
    # bottom text per page for the repetition test: zone blocks + footers found earlier
    bottom_tokens: dict[int, set[str]] = {}
    for i, page in enumerate(doc.pages):
        texts = [b.raw_text for b in page.furniture if b.kind in (BlockKind.FOOTER, BlockKind.PAGE_NUMBER)]
        if i in zones:
            texts += [b.raw_text for b in zones[i].blocks]
        bottom_tokens[i] = _tokens(" ".join(texts))

    moved = 0
    for i, z in zones.items():
        page = doc.pages[i]
        others = [other for j, other in bottom_tokens.items() if j != i and other]
        for b in _zone_footers(z, page.number, body_size, others):
            if page.layout is not None and _detach(page.layout, b):
                b.kind = BlockKind.FOOTER
                b.labels.add("footer:zone")
                page.furniture.append(b)
                moved += 1
    return moved


def _zone_footers(z: _Zone, page: int, body_size: float, others: list[set[str]]) -> list[Block]:
    """The footer blocks of a bottom zone; marks its footnotes on the way."""
    numbered = zone_page_number(z.blocks, page)
    footers: list[Block] = []
    rest: list[Block] = []
    for b in z.blocks:
        if is_footnote(b, body_size):
            b.kind = BlockKind.FOOTNOTE
            continue
        repeated = _repeated(_tokens(b.raw_text), others)
        if footer_score(b, body_size, z.gap, repeated, numbered is not None) >= THRESHOLD:
            footers.append(b)
        else:
            rest.append(b)
    # nothing below a footer is body text; logos/noise beside it and the page number belong to it too
    if footers:
        top = min(b.bbox.y0 for b in footers)
        footers += [b for b in rest if b.bbox.y0 >= top - 2 or looks_like_logo(b) or b is numbered]
    return footers


def _repeated(toks: set[str], others: list[set[str]]) -> bool:
    """OCR-tolerant repetition: most tokens of the block occur at another page bottom.
    A single-token block (e.g. a logo word) must occur at two other page bottoms."""
    if not toks:
        return False
    if len(toks) == 1:
        return sum(1 for o in others if toks <= o) >= 2
    return any(len(toks & o) / len(toks) >= 0.5 for o in others)
