"""Uses only the public API. tests/test_api.py runs `mypy --strict` on it."""

from dataclasses import replace
from datetime import datetime

from pazufa_pdf_parser import (
    Block,
    BlockKind,
    Issue,
    Metadata,
    Ocr,
    OcrMode,
    OcrUnavailableError,
    Page,
    PageReport,
    PageSource,
    ParseOptions,
    PazufaError,
    PdfDocument,
    PdfOpenError,
    Report,
    Severity,
    StepError,
    UnknownFormatError,
    __version__,
    parse,
    render,
)

OPTIONS = ParseOptions(ocr=OcrMode.AUTO, ocr_engine=Ocr(languages=("deu",), max_parallel=2))


def headings(doc: PdfDocument) -> list[Block]:
    return [b for b in doc.blocks if b.kind is BlockKind.HEADING]


def scanned(pages: tuple[Page, ...]) -> list[int]:
    return [p.number for p in pages if p.source is PageSource.OCR]


def created(metadata: Metadata) -> datetime | None:
    return metadata.created


def errors(report: Report) -> list[Issue]:
    return [i for i in report.issues if i.severity is Severity.ERROR]


def confidences(pages: tuple[PageReport, ...]) -> list[float]:
    return [p.ocr_confidence for p in pages if p.ocr_confidence is not None]


def cache_key(doc: PdfDocument) -> tuple[str, bool]:
    return doc.sha256, doc.report.parser_version == __version__


def load(path: str, cached: str | None) -> str:
    try:
        doc = PdfDocument.from_json(cached) if cached else parse(path, replace(OPTIONS, strict=True))
    except (PdfOpenError, OcrUnavailableError):
        return ""
    except StepError as e:
        return e.step
    except PazufaError:
        doc = parse(path, replace(OPTIONS, ocr=OcrMode.NEVER))
    try:
        html = render(doc, "html")
    except UnknownFormatError:
        html = ""
    return html + doc.text(pages=[1]) + doc.pages[0].text + doc.to_json()
