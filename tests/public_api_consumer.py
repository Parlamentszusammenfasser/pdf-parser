"""Uses only the public API. tests/test_api.py runs `mypy --strict` on it."""

from dataclasses import replace
from datetime import datetime

from pazufa_pdf_parser import (
    Block,
    BlockKind,
    Format,
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
    SchemaVersionError,
    Severity,
    Source,
    StepError,
    UnknownFormatError,
    __version__,
    parse,
    render,
)

FORMAT: Format = "html"
OPTIONS = ParseOptions(ocr=OcrMode.AUTO, ocr_engine=Ocr(languages=("deu",), max_parallel=2))


def headings(doc: PdfDocument) -> list[Block]:
    return [b for b in doc.blocks if b.kind is BlockKind.HEADING]


def scanned(pages: tuple[Page, ...]) -> list[int]:
    return [p.number for p in pages if p.source is PageSource.OCR]


def created(metadata: Metadata) -> datetime | None:
    return metadata.created


def problems(report: Report) -> list[Issue]:
    return [i for i in report.issues if i.severity >= Severity.WARNING]


def stub(text: str) -> PdfDocument:
    block = Block(page=1, kind=BlockKind.PARAGRAPH, text=text, bbox=(0.0, 0.0, 1.0, 1.0))
    return PdfDocument(
        sha256="",
        metadata=Metadata(title=None, author=None, created=None, modified=None, page_count=1),
        pages=(Page(number=1, source=PageSource.TEXT, blocks=(block,)),),
        report=Report(parser_version=__version__, pages=(), issues=()),
    )


def confidences(pages: tuple[PageReport, ...]) -> list[float]:
    return [p.ocr_confidence for p in pages if p.ocr_confidence is not None]


def cache_key(doc: PdfDocument) -> tuple[str, bool]:
    return doc.sha256, doc.report.parser_version == __version__


def load(src: Source, cached: str | None) -> str:
    try:
        doc = PdfDocument.from_json(cached) if cached else parse(src, replace(OPTIONS, strict=True))
    except SchemaVersionError:
        doc = parse(src, OPTIONS)
    except (PdfOpenError, OcrUnavailableError):
        return ""
    except StepError as e:
        return e.step
    except PazufaError:
        doc = parse(src, replace(OPTIONS, ocr=OcrMode.NEVER))
    try:
        html = render(doc, FORMAT)
    except UnknownFormatError:
        html = ""
    page = doc.pages[0]
    return html + doc.text(pages=[1]) + page.text() + page.furniture_text() + (page.printed_page or "") + doc.to_json()
