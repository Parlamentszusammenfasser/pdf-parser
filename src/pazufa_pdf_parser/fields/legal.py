"""Parsing the hierarchical structure of legal texts.

Levels (outer to inner)::

    0 part       Teil / Abschnitt / Kapitel / Titel, "I.", "A)"
    1 article    Artikel 1 / Art. 1
    2 section    § 1
    3 paragraph  (1)
    4 point      1.
    5 item       a)
    6 subitem    aa)
    7 subsubitem aaa)

Quoted amendment text („...“) is never parsed as structure; it is attached as
text to the node it belongs to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Block, BlockKind, Document, LegalNode, RegionKind

KIND_BY_LEVEL = ["part", "article", "section", "paragraph", "point", "item", "subitem", "subsubitem"]

PART_RE = re.compile(r"^(Teil|Abschnitt|Unterabschnitt|Kapitel|Titel|Buch)\s+([\dIVXLC]+[a-z]?)\.?\s*(.*)$", re.S)
ROMAN_RE = re.compile(r"^([IVX]{1,5})\.\s+(.{1,120})$", re.S)
LETTER_PART_RE = re.compile(r"^([A-H])\)\s+(.{1,80})$", re.S)
ARTICLE_RE = re.compile(r"^(?:Artikel|Art\.)\s*(\d+[a-z]?)\s*(.*)$", re.S)
SECTION_RE = re.compile(r"^§\s*(\d+[a-z]?)\s*(.*)$", re.S)
PARAGRAPH_RE = re.compile(r"^\((\d+[a-z]?)\)\s*(.*)$", re.S)
POINT_RE = re.compile(r"^(\d{1,3}[a-z]?)\.\s+(.*)$", re.S)
ITEM_RE = re.compile(r"^([a-z])\)\s*(.*)$", re.S)
SUBITEM_RE = re.compile(r"^([a-z])\1\)\s*(.*)$", re.S)
SUBSUBITEM_RE = re.compile(r"^([a-z])\1\1\)\s*(.*)$", re.S)

EXPLANATION_RE = re.compile(r"^(Begründung|Begründung\s*:|B\.\s*Besonderer Teil|Zu (Artikel|§)\s*\d+)", re.I)
OPEN_Q = '„"»'
CLOSE_Q = '“"«”'


# "§ 3 Abs. 2 wird ..." is a reference in running text, not a structural heading
_REF_CONT = re.compile(
    r"^\s*(?:Abs\.|Absatz\b|Satz\b|S\.\s*\d|Nr\.|Nummer\b|des\b|der\b|wird\b|werden\b|ist\b|erhält\b|und\b|bis\b|,)"
)


@dataclass
class _Match:
    level: int
    num: str
    rest: str


def _quote_balance(text: str) -> int:
    return sum(text.count(c) for c in "„»") - sum(text.count(c) for c in "“«”")


def match_structure(text: str, heading_like: bool) -> _Match | None:
    t = text.strip()
    if not t or t[0] in OPEN_Q:
        return None
    m = PART_RE.match(t)
    if m and len(t) < 200:
        return _Match(0, f"{m.group(1)} {m.group(2)}", m.group(3))
    m = ARTICLE_RE.match(t)
    if m and (heading_like or len(m.group(2)) < 150) and not _REF_CONT.match(m.group(2)):
        return _Match(1, m.group(1), m.group(2))
    m = SECTION_RE.match(t)
    if m and not _REF_CONT.match(m.group(2)):
        return _Match(2, m.group(1), m.group(2))
    m = PARAGRAPH_RE.match(t)
    if m:
        return _Match(3, m.group(1), m.group(2))
    m = SUBSUBITEM_RE.match(t)
    if m:
        return _Match(7, m.group(1) * 3, m.group(2))
    m = SUBITEM_RE.match(t)
    if m:
        return _Match(6, m.group(1) * 2, m.group(2))
    m = ITEM_RE.match(t)
    if m:
        return _Match(5, m.group(1), m.group(2))
    m = POINT_RE.match(t)
    if m:
        return _Match(4, m.group(1), m.group(2))
    if heading_like:
        m = ROMAN_RE.match(t)
        if m:
            return _Match(0, m.group(1), m.group(2))
        m = LETTER_PART_RE.match(t)
        if m:
            return _Match(0, m.group(1), m.group(2))
    return None


def _split_heading(level: int, rest: str) -> tuple[str, str]:
    """For headed levels, separate a short heading from body text."""
    rest = rest.strip()
    if level > 2 or not rest:
        return "", rest
    first, _, remainder = rest.partition("\n")
    if level <= 2 and len(first) <= 120 and not first.endswith((".", ";", ",")):
        heading = first
        if remainder and level <= 1 and len(remainder) < 120 and "\n" not in remainder and not remainder.endswith("."):
            heading = f"{first} {remainder}"
            remainder = ""
        return heading.strip(), remainder.strip()
    return "", rest


def parse_legal_texts(items: list[tuple[str, bool]]) -> list[LegalNode]:
    """Parse ``(text, heading_like)`` items into a forest of legal nodes."""
    roots: list[LegalNode] = []
    stack: list[tuple[int, LegalNode]] = []
    quote_depth = 0
    pending_heading_for: LegalNode | None = None

    def attach_text(t: str) -> None:
        if stack:
            stack[-1][1].text.append(t)
        else:
            roots.append(LegalNode(kind="text", text=[t]))

    for text, heading_like in items:
        t = text.strip()
        if not t:
            continue
        if quote_depth > 0:
            attach_text(t)
            quote_depth = max(0, quote_depth + _quote_balance(t))
            continue
        m = match_structure(t, heading_like)
        if m is None:
            if (
                pending_heading_for is not None
                and len(t) <= 160
                and "\n" not in t.strip()
                and not t.endswith((".", ";", ",", ":"))
            ):
                pending_heading_for.heading = t
                pending_heading_for = None
                continue
            pending_heading_for = None
            attach_text(t)
            quote_depth = max(0, _quote_balance(t))
            continue
        pending_heading_for = None
        heading, body = _split_heading(m.level, m.rest)
        node = LegalNode(kind=KIND_BY_LEVEL[m.level], num=m.num, heading=heading)
        if body:
            node.text.append(body)
        while stack and stack[-1][0] >= m.level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((m.level, node))
        if m.level <= 2 and not heading and not body:
            pending_heading_for = node
        quote_depth = max(0, _quote_balance(m.rest))
    return roots


def _items(blocks: list[Block]) -> list[tuple[str, bool]]:
    out = []
    for b in blocks:
        t = (b.text or b.raw_text).strip()
        if not t or b.labels & {"email_header", "salutation", "closing", "signature"}:
            continue
        out.append((t, b.kind is BlockKind.HEADING))
    return out


def find_law_span(blocks: list[Block]) -> tuple[int, int] | None:
    """Index range of the normative text: from the first article/§ heading to the explanation."""
    start = None
    for i, b in enumerate(blocks):
        t = (b.text or b.raw_text).strip()
        m = match_structure(t, b.kind is BlockKind.HEADING)
        if m and m.level in (1, 2):
            start = i
            break
    if start is None:
        return None
    end = len(blocks)
    for j in range(start + 1, len(blocks)):
        t = (blocks[j].text or blocks[j].raw_text).strip()
        if EXPLANATION_RE.match(t) and len(t) < 120:
            end = j
            break
    return start, end


def synopsis_columns(doc: Document) -> list[dict]:
    """Collect two-column synopsis regions across consecutive pages."""
    out: list[dict] = []
    current: dict | None = None
    last_page = -10
    for page in doc.pages:
        if page.layout is None:
            continue
        for r in page.layout.iter_regions():
            if r.kind is not RegionKind.COLUMNS or not r.synopsis:
                continue
            left = list(r.children[0].iter_blocks())
            right = list(r.children[1].iter_blocks())
            if current is None or page.number - last_page > 1:
                current = {"left_blocks": [], "right_blocks": [], "pages": []}
                out.append(current)
            current["left_blocks"].extend(left)
            current["right_blocks"].extend(right)
            current["pages"].append(page.number)
            last_page = page.number
    for syn in out:
        for side in ("left", "right"):
            blocks = syn[f"{side}_blocks"]
            label = ""
            if (
                blocks
                and (blocks[0].text or blocks[0].raw_text).strip().endswith(":")
                and len((blocks[0].text or "").strip()) < 140
            ):
                label = " ".join((blocks[0].text or blocks[0].raw_text).split()).rstrip(":")
                blocks = blocks[1:]
            syn[f"{side}_label"] = label
            syn[side] = parse_legal_texts(_items(blocks))
    return out


def extract_legal_structure(doc: Document) -> list[LegalNode]:
    blocks = [b for b in doc.body_blocks if not _in_synopsis(doc, b)]
    span = find_law_span(blocks)
    if span is None:
        return []
    start, end = span
    return parse_legal_texts(_items(blocks[start:end]))


def _in_synopsis(doc: Document, block: Block) -> bool:
    page = doc.pages[block.page - 1]
    if page.layout is None:
        return False
    for r in page.layout.iter_regions():
        if r.synopsis and any(b is block for b in r.iter_blocks()):
            return True
    return False
