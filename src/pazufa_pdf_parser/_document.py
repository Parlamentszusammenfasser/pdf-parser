"""Public parse result: the immutable PdfDocument that parse() returns."""

from __future__ import annotations

import json
import operator
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
from importlib.metadata import version
from typing import Any

from ._errors import PazufaError, SchemaVersionError

PARSER_VERSION = version("pazufa-pdf-parser")
# bump when a key is removed or changes meaning, or an enum gains a value; new keys need no bump. A bump
# drops the old version from _READABLE_VERSIONS unless from_json learns to upgrade it.
SCHEMA_VERSION = 2
_READABLE_VERSIONS = {2}  # 1: page OCR details in report.pages, continuations moved into the previous page


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

    @property
    def is_furniture(self) -> bool:
        return self in (BlockKind.HEADER, BlockKind.FOOTER, BlockKind.PAGE_NUMBER)


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    # a StrEnum orders alphabetically ("error" < "info"), so `>= WARNING` would drop errors
    def _compare(self, other: object, op: Callable[[int, int], bool]) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        order = list(Severity)
        return op(order.index(self), order.index(Severity(other)))

    def __lt__(self, other: object) -> bool:
        return self._compare(other, operator.lt)

    def __le__(self, other: object) -> bool:
        return self._compare(other, operator.le)

    def __gt__(self, other: object) -> bool:
        return self._compare(other, operator.gt)

    def __ge__(self, other: object) -> bool:
        return self._compare(other, operator.ge)


@dataclass(frozen=True, slots=True, kw_only=True)
class Issue:
    severity: Severity
    #: part of the parser that recorded it: "extract", "ocr", "layout", "garbled", "furniture", "page_numbers",
    #: "sanitize" or "flow"; stable
    step: str
    #: what happened, e.g. "ocr_unavailable", "page_unloadable"; stable, one per message pattern
    code: str
    message: str
    page: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Block:
    page: int  # 1-based PDF page
    kind: BlockKind
    text: str  # sanitized, never empty
    bbox: tuple[float, float, float, float]  # points, top-left origin, page rotation applied
    level: int = 0  # heading level, 1 = top
    #: the paragraph goes on in the next page's first body block; ``text()`` joins the two with a space
    continues: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Page:
    number: int  # 1-based PDF page
    width: float  # points, as shown: page rotation applied
    height: float
    source: PageSource
    blocks: tuple[Block, ...]  # headers, body in reading order, footers and page numbers, margin notes and noise
    #: printed page number ("259", "II"); None when none was found, e.g. on a single page without "Seite N"
    printed_page: str | None = None
    #: the text layer is missing or garbled and OCR did not replace it (off, unavailable, over the limit, failed)
    needs_ocr: bool = False
    #: why the page was or was not OCRed, and why wanted OCR did not run; for people, not matching
    ocr_reason: str = ""
    ocr_confidence: float | None = None  # mean tesseract word confidence 0..100 of an OCRed page

    def text(self) -> str:
        """Sanitized body text of this page."""
        return _body_text(self.blocks)

    def furniture_text(self) -> str:
        """Headers, footers and page numbers joined by newlines: headers top-down, then the rest top-down."""
        return "\n".join(b.text for b in self.blocks if b.kind.is_furniture and b.text)


@dataclass(frozen=True, slots=True, kw_only=True)
class Metadata:
    title: str | None
    author: str | None
    created: datetime | None
    modified: datetime | None
    page_count: int  # pages in the PDF, also when only some were parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class Report:
    parser_version: str
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
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
        if isinstance(pages, str):  # "3" would iterate as {"3"} and match no page
            raise TypeError("pages must be page numbers, e.g. [3], not a string")
        wanted = None if pages is None else set(pages)
        return _body_text(b for b in self.blocks if wanted is None or b.page in wanted)

    def to_json(self) -> str:
        data = {"schema_version": SCHEMA_VERSION, **asdict(self)}
        return json.dumps(data, ensure_ascii=False, default=datetime.isoformat)

    @classmethod
    def from_json(cls, s: str | bytes) -> PdfDocument:
        """Load what :meth:`to_json` wrote, also by another version of this parser of the same schema.

        Unknown keys are ignored and missing ones take the field's default. Raises SchemaVersionError
        for JSON of a schema this parser cannot read (parse the PDF again), PazufaError for invalid
        JSON or missing required fields. Value types are not checked: hand-edited JSON with e.g. a
        number as text loads and fails later.
        """
        try:
            data = json.loads(s)
            found = data["schema_version"]
            if type(found) is not int or found < 1:
                raise PazufaError(f"not a PdfDocument JSON: schema_version {found!r}")
            if found not in _READABLE_VERSIONS:
                raise SchemaVersionError(
                    f"PdfDocument JSON has schema_version {found}; this parser reads {sorted(_READABLE_VERSIONS)}"
                )
            return _load(
                cls,
                data,
                metadata=lambda m: _load(Metadata, m, created=_datetime, modified=_datetime),
                pages=lambda ps: tuple(_load(Page, p, source=PageSource, blocks=_blocks) for p in ps),
                report=lambda r: _load(
                    Report, r, issues=lambda xs: tuple(_load(Issue, i, severity=Severity) for i in xs)
                ),
            )
        # truncated cache files, other tools' JSON, absurd nesting
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as e:
            raise PazufaError(f"not a PdfDocument JSON: {e!r}") from e


def _load(cls: Any, data: dict[str, Any], **convert: Callable[[Any], Any]) -> Any:
    """Build ``cls`` from the keys it knows: JSON from a newer parser may carry more."""
    known = {f.name for f in fields(cls)}
    return cls(**{k: convert[k](v) if k in convert else v for k, v in data.items() if k in known})


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _blocks(blocks: list[dict[str, Any]]) -> tuple[Block, ...]:
    return tuple(_load(Block, b, kind=BlockKind, bbox=tuple) for b in blocks)


def _body_text(blocks: Iterable[Block]) -> str:
    """Body blocks separated by blank lines. A paragraph continued on the next page is joined to its
    continuation; the footnotes printed between the two follow the joined paragraph."""
    out: list[str] = []
    held: list[str] = []
    open_on: int | None = None  # the page the open paragraph continues on
    for b in blocks:
        if not b.kind.is_body:
            continue
        if open_on is not None and b.kind is BlockKind.FOOTNOTE:
            held.append(b.text)
            continue
        if b.page == open_on:
            out[-1] += " " + b.text
        else:
            out += held
            held = []
            out.append(b.text)
        open_on = b.page + 1 if b.continues else None
    return "\n\n".join(out + held)
