"""Core data model shared by every pipeline stage.

Coordinates are PDF points in *view space*: origin top-left of the page as it
is displayed (i.e. after applying the page's ``/Rotate``), x to the right,
y downwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Iterator

from .._document import BlockKind, Issue, PageSource, Severity

# --------------------------------------------------------------------------- geometry


@dataclass(frozen=True, slots=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def union(self, other: BBox) -> BBox:
        return BBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def x_overlap(self, other: BBox) -> float:
        return max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))

    def y_overlap(self, other: BBox) -> float:
        return max(0.0, min(self.y1, other.y1) - max(self.y0, other.y0))

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def to_list(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]

    @staticmethod
    def enclosing(boxes: Iterable[BBox]) -> BBox:
        it = iter(boxes)
        try:
            acc = next(it)
        except StopIteration:
            return BBox(0, 0, 0, 0)
        for b in it:
            acc = acc.union(b)
        return acc


# --------------------------------------------------------------------------- enums


class TextSource(StrEnum):
    PDF = "pdf"  # text layer of the PDF
    OCR = "ocr"  # recognised by OCR


class RegionKind(StrEnum):
    STACK = "stack"  # children stacked vertically
    COLUMNS = "columns"  # children side by side, read left to right
    LEAF = "leaf"  # holds blocks


# --------------------------------------------------------------------------- text primitives


@dataclass(slots=True)
class Word:
    text: str
    bbox: BBox
    size: float = 0.0  # font size in pt (OCR: estimated from glyph height)
    bold: bool = False
    italic: bool = False
    font: str = ""
    source: TextSource = TextSource.PDF
    confidence: float | None = None  # OCR confidence 0..100
    angle: int = 0  # text direction in degrees, 0 = upright
    invisible: bool = False  # text render mode 3 (e.g. an existing OCR layer)


@dataclass(slots=True)
class Line:
    words: list[Word]
    bbox: BBox
    text: str  # words joined; large horizontal gaps become "\t"

    @property
    def size(self) -> float:
        sizes = [w.size for w in self.words if w.size > 0]
        if not sizes:
            return self.bbox.height
        sizes.sort()
        return sizes[len(sizes) // 2]

    @property
    def bold(self) -> bool:
        chars = sum(len(w.text) for w in self.words) or 1
        return sum(len(w.text) for w in self.words if w.bold) / chars >= 0.6

    @property
    def confidence(self) -> float | None:
        confs = [w.confidence for w in self.words if w.confidence is not None]
        return sum(confs) / len(confs) if confs else None


@dataclass(slots=True)
class Block:
    lines: list[Line]
    bbox: BBox
    page: int
    kind: BlockKind = BlockKind.PARAGRAPH
    level: int = 0  # heading level (1 = top) for HEADING blocks
    region: str = ""  # id of the layout region holding the block
    column: int = 0  # column index inside a COLUMNS region (0 = left / single)
    text: str = ""  # sanitized text, set by the sanitize step
    labels: set[str] = field(default_factory=set)  # set by layout steps, e.g. footer:zone, merged_into_previous

    @property
    def raw_text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def size(self) -> float:
        sizes = sorted(line.size for line in self.lines)
        return sizes[len(sizes) // 2] if sizes else 0.0

    @property
    def bold(self) -> bool:
        return bool(self.lines) and all(line.bold for line in self.lines)

    @property
    def confidence(self) -> float | None:
        confs = [c for line in self.lines if (c := line.confidence) is not None]
        return sum(confs) / len(confs) if confs else None


@dataclass(slots=True)
class Region:
    kind: RegionKind
    bbox: BBox
    id: str = ""
    children: list[Region] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    # set on COLUMNS regions whose columns are parallel versions of the same text
    synopsis: bool = False
    # COLUMNS region whose narrow right column is an aside (letter sidebar): read it first
    aside_first: bool = False
    # transient: words of a LEAF before blocks are built
    words: list[Word] = field(default_factory=list, repr=False)

    def iter_blocks(self) -> Iterator[Block]:
        """Blocks in reading order."""
        if self.kind is RegionKind.LEAF:
            yield from self.blocks
        else:
            children = self.children
            if self.aside_first and len(children) == 2:
                children = [children[1], children[0]]
            for child in children:
                yield from child.iter_blocks()

    def iter_regions(self) -> Iterator[Region]:
        yield self
        for child in self.children:
            yield from child.iter_regions()


@dataclass(slots=True)
class Page:
    number: int  # 1-based
    width: float
    height: float
    rotation: int = 0
    source: PageSource = PageSource.TEXT
    words: list[Word] = field(default_factory=list)  # every word extracted from the page
    lines: list[Line] = field(default_factory=list)  # all lines (incl. furniture), top-down
    furniture: list[Block] = field(default_factory=list)  # headers, footers, page numbers
    extras: list[Block] = field(default_factory=list)  # marginal / noise blocks
    layout: Region | None = None  # body layout tree
    printed_page: str | None = None  # set by the furniture step
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> list[Block]:
        """Body blocks in reading order."""
        return list(self.layout.iter_blocks()) if self.layout else []

    @property
    def all_blocks(self) -> list[Block]:
        """Every block, ordered: headers, body, footers/page numbers, extras."""
        top = [b for b in self.furniture if b.kind is BlockKind.HEADER]
        bottom = [b for b in self.furniture if b.kind is not BlockKind.HEADER]
        top.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
        bottom.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
        return top + self.blocks + bottom + self.extras


@dataclass(slots=True)
class Document:
    source: str | None = None
    sha256: str = ""
    pdf_info: dict[str, Any] = field(default_factory=dict)
    pages: list[Page] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def body_blocks(self) -> list[Block]:
        return [b for p in self.pages for b in p.blocks]

    def body_text(self) -> str:
        return "\n\n".join(b.text or b.raw_text for b in self.body_blocks)

    def issue(self, severity: Severity, step: str, message: str, page: int | None = None) -> None:
        self.issues.append(Issue(severity=severity, step=step, message=message, page=page))
