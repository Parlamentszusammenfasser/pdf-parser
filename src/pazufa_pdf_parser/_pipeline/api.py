"""parse(): run the pipeline and turn its internal Document into the public PdfDocument."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .._document import PARSER_VERSION, Block, Metadata, Page, PdfDocument, Report
from .._options import ParseOptions
from . import model
from .pipeline import Pipeline
from .source import Source


def parse(src: Source, options: ParseOptions | None = None) -> PdfDocument:
    """Parse a PDF (path, bytes or binary file object).

    Recoverable problems are recorded in ``doc.report.issues`` (``ParseOptions(strict=True)``
    raises instead); an unreadable PDF raises :class:`PdfOpenError`.
    """
    return build_document(Pipeline().run(src, options))


def _block(b: model.Block) -> Block:
    x0, y0, x1, y1 = b.bbox.to_list()
    return Block(page=b.page, kind=b.kind, text=b.text, bbox=(x0, y0, x1, y1), level=b.level, continues=b.continues)


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
        pages=tuple(
            Page(
                number=p.number,
                width=p.width,
                height=p.height,
                source=p.source,
                # a paragraph joined to the previous block leaves its own empty
                blocks=tuple(blk for blk in map(_block, p.all_blocks) if blk.text),
                printed_page=p.printed_page,
                needs_ocr=p.needs_ocr,
                ocr_reason=p.ocr_reason,
                ocr_confidence=p.ocr_confidence,
            )
            for p in doc.pages
        ),
        report=Report(parser_version=PARSER_VERSION, issues=tuple(doc.issues)),
    )
