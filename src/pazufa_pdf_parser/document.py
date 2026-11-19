"""Public parse result: the immutable PdfDocument that parse() returns."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from importlib.metadata import version
from typing import Any

from .errors import PazufaError

PARSER_VERSION = version("pazufa-pdf-parser")
# bump when to_json's layout changes; from_json reads only this version
SCHEMA_VERSION = 1


class PageSource(StrEnum):
    TEXT = "text"
    OCR = "ocr"
    EMPTY = "empty"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    HEADER = "header"  # running page header (furniture)
    FOOTER = "footer"  # running page footer (furniture)
    PAGE_NUMBER = "page_number"
    MARGINAL = "marginal"  # rotated / out-of-flow text (e.g. vertical margin notes)
    NOISE = "noise"  # OCR garbage, scanner artifacts
    FOOTNOTE = "footnote"  # numbered note at the page bottom (content, kept in the text)

    @property
    def is_body(self) -> bool:
        return self in (BlockKind.PARAGRAPH, BlockKind.HEADING, BlockKind.LIST_ITEM, BlockKind.FOOTNOTE)


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    step: str  # pipeline step that recorded it, e.g. "ocr"
    message: str
    page: int | None = None


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

    @classmethod
    def from_json(cls, s: str | bytes) -> PdfDocument:
        """Load what :meth:`to_json` wrote.

        Raises PazufaError for another schema version, invalid JSON or missing fields. Value types are
        not checked: hand-edited JSON with e.g. a number as text loads and fails later.
        """
        try:
            data = json.loads(s)
            found = data["schema_version"]
            if found != SCHEMA_VERSION:
                raise PazufaError(f"PdfDocument JSON has schema_version {found!r}; this parser reads {SCHEMA_VERSION}")
            meta, report = data["metadata"], data["report"]
            return cls(
                sha256=data["sha256"],
                metadata=Metadata(
                    meta["title"],
                    meta["author"],
                    _datetime(meta["created"]),
                    _datetime(meta["modified"]),
                    meta["page_count"],
                ),
                pages=tuple(_page(p) for p in data["pages"]),
                report=Report(
                    report["parser_version"],
                    tuple(PageReport(**r) for r in report["pages"]),
                    tuple(Issue(**i | {"severity": Severity(i["severity"])}) for i in report["issues"]),
                ),
            )
        # truncated cache files, other tools' JSON, absurd nesting
        except (ValueError, TypeError, KeyError, RecursionError) as e:
            raise PazufaError(f"not a PdfDocument JSON: {e!r}") from e


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _page(p: dict[str, Any]) -> Page:
    blocks = (Block(**b | {"kind": BlockKind(b["kind"]), "bbox": tuple(b["bbox"])}) for b in p["blocks"])
    return Page(p["number"], PageSource(p["source"]), tuple(blocks))


def _body_text(blocks: Iterable[Block]) -> str:
    return "\n\n".join(b.text for b in blocks if b.kind.is_body and b.text)
