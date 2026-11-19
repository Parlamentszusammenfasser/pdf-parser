"""pazufa_pdf_parser - clean text and layout from PDF documents.

Quick start::

    from pazufa_pdf_parser import parse

    doc = parse("letter.pdf")   # OCR is used automatically for scans
    print(doc.text())

The names in ``__all__`` are the public API. ``pazufa_pdf_parser._pipeline``
is internal and changes without notice.
"""

from ._pipeline.api import parse
from ._pipeline.render import render
from .document import (
    PARSER_VERSION,
    Block,
    BlockKind,
    Issue,
    Metadata,
    Page,
    PageReport,
    PageSource,
    PdfDocument,
    Report,
    Severity,
)
from .errors import OcrUnavailableError, PazufaError, PdfOpenError, StepError, UnknownFormatError
from .options import Ocr, OcrMode, ParseOptions

__version__ = PARSER_VERSION

__all__ = [
    "parse",
    "ParseOptions",
    "OcrMode",
    "Ocr",
    "PdfDocument",
    "Page",
    "Block",
    "BlockKind",
    "PageSource",
    "Metadata",
    "Report",
    "PageReport",
    "Issue",
    "Severity",
    "render",
    "PazufaError",
    "PdfOpenError",
    "OcrUnavailableError",
    "StepError",
    "UnknownFormatError",
]
