"""Turning the lines of a layout leaf into blocks (paragraphs, list items, headings)."""

from __future__ import annotations

import re
from statistics import median

from ..model import BBox, Block, BlockKind, Line, Region, RegionKind
from ..sanitize import HYPHENS
from .lines import build_lines

LIST_MARKER_RE = re.compile(
    r"""^(
        [\-–•▪●○◦■□►➢✓*]\s              # bullets
      | \(?\d{1,3}[a-z]?\)\s             # (1)  1)  (1a)
      | \d{1,3}(\.\d{1,3})*\.?\s(?=\S)    # 1.  1.2  1.2.3
      | \(?[a-z]{1,3}\)\s                # a)  aa)  (b)
      | [IVXLC]{1,6}\.\s                 # I.  II.
      | [A-Z][.)]\s                      # A)  B.
      | §\s?\d                           # § 1
      | Art(ikel|\.)\s?\d                # Artikel 1 / Art. 1
    )""",
    re.X,
)
_DATE_LIKE_RE = re.compile(
    r"^\d{1,3}\.\s?(Wahlperiode|Legislaturperiode|Sitzung|Plenum|Plenarsitzung|Jahrhundert|Lesung|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d{1,2}\.)",
    re.I,
)
_END_PUNCT = tuple(".:;!?")
_HYPHENATED_END_RE = re.compile(rf"[a-zäöüß][{HYPHENS}]$")
_LOWER_START_RE = re.compile(r"[a-zäöüß]")


def starts_with_marker(text: str) -> bool:
    t = text.lstrip()
    return bool(LIST_MARKER_RE.match(t)) and not _DATE_LIKE_RE.match(t)


def _all_bold(line: Line) -> bool:
    return bool(line.words) and all(w.bold for w in line.words)


def run_in_label(line: Line) -> int:
    """Number of words of a bold label ending in ':' that starts the line and is
    followed by regular text (0 if there is none)."""
    words = line.words
    if len(words) < 2 or not words[0].bold:
        return 0
    for i, w in enumerate(words[:14]):
        if not w.bold:
            return 0
        if w.text.endswith(":"):
            return i + 1 if i + 1 < len(words) and not words[i + 1].bold else 0
    return 0


def _is_ocr(line: Line) -> bool:
    return any(w.confidence is not None for w in line.words)


def _continues_word(cur: Line, nxt: Line) -> bool:
    """The next line finishes a word the current line breaks off with a hyphen."""
    if starts_with_marker(nxt.text):
        return False  # "a) Vor-" / "b) Nachname": the next item starts
    return bool(_HYPHENATED_END_RE.search(cur.text) and _LOWER_START_RE.match(nxt.text))


def _gap(a: Line, b: Line) -> float:
    return b.bbox.y0 - a.bbox.y1


def _pitches(lines: list[Line]) -> list[float]:
    # line pitch (top-to-top) is more stable than gaps, esp. for OCR boxes whose
    # heights vary with ascenders/descenders
    return [b.bbox.y0 - a.bbox.y0 for a, b in zip(lines, lines[1:])]


def line_pitch(lines: list[Line]) -> float:
    """The typical pitch of consecutive lines: the leading of the running text."""
    h = median(ln.bbox.height for ln in lines)
    pos = [p for p in _pitches(lines) if p > 0.5 * h]
    if len(pos) < 3:
        # too few lines to know the leading: assume at most ~1.3 line heights
        return min(median(pos) if pos else h * 1.2, h * 1.3)
    return median(pos)


def split_blocks(lines: list[Line], page: int, region_id: str = "", pitch: float | None = None) -> list[Block]:
    """Split vertically ordered lines of one flow region into blocks. ``pitch``: the leading of the area the
    region was cut from, for a region of too few running lines to show its own."""
    if not lines:
        return []
    h = median(ln.bbox.height for ln in lines)
    pitches = _pitches(lines)
    typical = line_pitch(lines) if pitch is None else min(line_pitch(lines), pitch)
    gaps = [_gap(a, b) for a, b in zip(lines, lines[1:])]
    right = max(ln.bbox.x1 for ln in lines)
    left = min(ln.bbox.x0 for ln in lines)
    width = max(right - left, 1.0)

    blocks: list[list[Line]] = [[lines[0]]]
    for i, (cur, nxt) in enumerate(zip(lines, lines[1:])):
        size = max(cur.size, nxt.size, 1.0)
        brk = False
        if pitches[i] > typical + 0.4 * min(h, size * 1.3) and gaps[i] > 0.25 * h:
            brk = True
        elif nxt.bbox.x0 > cur.bbox.x1 or nxt.bbox.x1 < cur.bbox.x0:
            brk = True
        elif _continues_word(cur, nxt):
            pass  # a protocol ToC entry turns from bold to regular inside "Staats-" / "vertragsentwürfe"
        elif abs(cur.size - nxt.size) > (0.35 if _is_ocr(cur) or _is_ocr(nxt) else 0.15) * size:
            brk = True
        elif _all_bold(cur) != _all_bold(nxt) and (len(cur.text) < 120 or len(nxt.text) < 120):
            brk = True
        elif run_in_label(nxt) and (not run_in_label(cur) or run_in_label(nxt) >= 2):
            brk = True  # "Präsidentin X:" / "Abg. Y (SPD):" speaker labels, bold run-in headings
        else:
            short = cur.bbox.x1 < right - max(0.15 * width, 3 * size)
            ends = cur.text.rstrip().endswith(_END_PUNCT)
            if starts_with_marker(nxt.text) and (ends or short or starts_with_marker(cur.text)):
                brk = True
            elif short and ends and nxt.bbox.x0 > cur.bbox.x0 + 0.8 * size:
                brk = True  # first-line indent after a short closing line
        if brk:
            blocks.append([nxt])
        else:
            blocks[-1].append(nxt)
    out: list[Block] = []
    for bl in blocks:
        kind = BlockKind.LIST_ITEM if starts_with_marker(bl[0].text) else BlockKind.PARAGRAPH
        out.append(
            Block(
                lines=bl,
                bbox=BBox.enclosing(ln.bbox for ln in bl),
                page=page,
                kind=kind,
                region=region_id,
            )
        )
    return out


def fill_leaves(region: Region, page: int, pitch: float | None = None) -> None:
    """Build blocks for every leaf of a region tree (consumes the leaf words)."""
    if pitch is None and any(c.ruled for c in region.children):
        # the rows of a table cut the text between them into leaves of a heading and an item or two, whose
        # paragraph gaps would pass for the leading (17/1104 p. 36); the whole area's lines show it
        pitch = line_pitch(build_lines([w for r in region.iter_regions() for w in r.words]))
    if region.kind is RegionKind.LEAF:
        region.blocks = split_blocks(build_lines(region.words), page, region.id, pitch)
        region.words = []
    for c in region.children:
        fill_leaves(c, page, pitch)


_HEADING_PATTERNS = [
    re.compile(r"^(Artikel|Art\.)\s*\d+[a-z]?$"),
    re.compile(r"^§\s*\d+[a-z]?(\s+\S.*)?$"),
    re.compile(r"^(Teil|Abschnitt|Kapitel|Titel|Unterabschnitt|Buch)\s+[\dIVXLC]+[a-z]?\b"),
    re.compile(r"^[A-H]\)\s+\S"),
    re.compile(r"^[IVX]{1,5}\.\s+\S"),
]


def classify_headings(blocks: list[Block], body_size: float) -> None:
    """Mark heading blocks and assign levels using document-wide font statistics."""
    bold_chars = sum(len(ln.text) for b in blocks for ln in b.lines if ln.bold)
    all_chars = sum(len(ln.text) for b in blocks for ln in b.lines) or 1
    bold_is_rare = bold_chars / all_chars < 0.35
    candidates: list[tuple[Block, float]] = []
    for b in blocks:
        if b.kind is not BlockKind.PARAGRAPH and b.kind is not BlockKind.LIST_ITEM:
            continue
        text = " ".join(ln.text for ln in b.lines).strip()
        if not text or len(b.lines) > 3 or len(text) > 160:
            continue
        if text.endswith((".", ",", ";")) and not re.search(r"\b(Art|Nr|Abs|Drs|Ziff|lit)\.$", text):
            continue
        if sum(c.isalpha() for c in text) < 3:
            continue
        size = b.size
        ocr = any(w.confidence is not None for ln in b.lines for w in ln.words)
        bigger = size >= body_size * (1.3 if ocr else 1.15)
        bold = b.bold and bold_is_rare and size >= body_size * 0.95
        pattern = any(p.match(text) for p in _HEADING_PATTERNS) and len(text) < 100
        if bigger or bold or (pattern and (b.bold or len(b.lines) == 1)):
            candidates.append((b, size if (bigger or bold) else body_size))
    if not candidates:
        return
    sizes = sorted({round(s, 0) for _, s in candidates}, reverse=True)
    for b, s in candidates:
        level = sizes.index(round(s, 0)) + 1
        if b.bold and round(s, 0) == round(body_size, 0):
            level = len(sizes) + (0 if level == len(sizes) else 1)
        b.kind = BlockKind.HEADING
        b.level = max(1, min(level, 6))
