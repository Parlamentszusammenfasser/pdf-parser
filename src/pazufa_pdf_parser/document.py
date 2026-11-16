"""Public parse result: an immutable PdfDocument built from the pipeline's internal Document."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import version

from . import model
from .model import BlockKind, Issue, PageSource

PARSER_VERSION = version("pazufa-pdf-parser")
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Block:
    page: int  # 1-based PDF page the block starts on
    kind: BlockKind
    text: str  # sanitized; empty when the paragraph was joined to the previous block
    bbox: tuple[float, float, float, float]  # points, top-left origin, page rotation applied
    level: int = 0  # heading level, 1 = top


@dataclass(frozen=True, slots=True)
class Page:
    number: int  # 1-based PDF page
    source: PageSource
    blocks: tuple[Block, ...]  # headers, body in reading order, footers and page numbers, margin notes and noise

    @property
    def text(self) -> str:
        return _body_text(self.blocks)


@dataclass(frozen=True, slots=True)
class Metadata:
    title: str | None
    author: str | None
    created: datetime | None
    modified: datetime | None
    page_count: int  # pages in the PDF, also when only some were parsed


@dataclass(frozen=True, slots=True)
class PageReport:
    number: int
    ocr_reason: str  # why the page was or was not OCRed
    ocr_confidence: float | None  # mean tesseract word confidence 0..100


@dataclass(frozen=True, slots=True)
class Report:
    parser_version: str
    pages: tuple[PageReport, ...]
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class PdfDocument:
    sha256: str
    metadata: Metadata
    pages: tuple[Page, ...]
    report: Report

    @property
    def blocks(self) -> tuple[Block, ...]:
        return tuple(b for p in self.pages for b in p.blocks)

    def text(self, pages: Iterable[int] | None = None) -> str:
        """Sanitized body text of all pages, or of the given 1-based page numbers."""
        wanted = None if pages is None else set(pages)
        return _body_text(b for b in self.blocks if wanted is None or b.page in wanted)

    def to_json(self) -> str:
        data = {"schema_version": SCHEMA_VERSION, **asdict(self)}
        return json.dumps(data, ensure_ascii=False, default=datetime.isoformat)


def _body_text(blocks: Iterable[Block]) -> str:
    return "\n\n".join(b.text for b in blocks if b.kind.is_body and b.text)


def _block(b: model.Block) -> Block:
    text = b.text.strip()
    text = " ".join(text.split()) if b.kind is BlockKind.HEADING else re.sub(r"\n{3,}", "\n\n", text)
    x0, y0, x1, y1 = b.bbox.to_list()
    return Block(b.page, b.kind, text, (x0, y0, x1, y1), b.level)


# D:YYYYMMDDHHmmSS+HH'mm' (PDF 1.7, 7.9.4); everything after the year is optional
_PDF_DATE = re.compile(r"(?:D:)?(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?(\d\d)?(?:([-+Z])(\d\d)?'?(\d\d)?'?)?")


def pdf_date(value: str | None) -> datetime | None:
    """Parse a PDF date string; None when missing or invalid. Without a zone the datetime is naive."""
    m = _PDF_DATE.fullmatch((value or "").strip())
    if not m:
        return None
    year, month, day, hour, minute, second, sign, tz_hours, tz_minutes = m.groups()
    try:
        tz = None
        if sign == "Z":
            tz = timezone.utc
        elif sign:
            offset = timedelta(hours=int(tz_hours or 0), minutes=int(tz_minutes or 0))
            tz = timezone(offset if sign == "+" else -offset)
        return datetime(
            int(year),
            int(month or 1),
            int(day or 1),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=tz,
        )
    except ValueError:  # month 13, zone offset of 24 h or more
        return None


def build_document(doc: model.Document) -> PdfDocument:
    info = doc.pdf_info
    return PdfDocument(
        sha256=doc.sha256,
        metadata=Metadata(
            title=info.get("Title"),
            author=info.get("Author"),
            created=pdf_date(info.get("CreationDate")),
            modified=pdf_date(info.get("ModDate")),
            page_count=info["page_count"],
        ),
        pages=tuple(Page(p.number, p.source, tuple(_block(b) for b in p.all_blocks)) for p in doc.pages),
        report=Report(
            parser_version=PARSER_VERSION,
            pages=tuple(
                PageReport(p.number, p.stats.get("ocr_reason", ""), p.stats.get("ocr_mean_confidence"))
                for p in doc.pages
            ),
            issues=tuple(doc.issues),
        ),
    )
