"""pazufa_pdf_parser - clean text and layout from PDF documents.

Quick start::

    from pazufa_pdf_parser import parse

    doc = parse("letter.pdf")   # OCR is used automatically for scans
    print(doc.text())

The names in ``__all__`` are the public API. ``pazufa_pdf_parser._pipeline``
is internal and changes without notice.
"""

from ._document import (
    PARSER_VERSION,
    Block,
    BlockKind,
    Issue,
    Metadata,
    Page,
    PageSource,
    PdfDocument,
    Report,
    Severity,
)
from ._errors import OcrUnavailableError, PazufaError, PdfOpenError, SchemaVersionError, StepError, UnknownFormatError
from ._options import Ocr, OcrMode, ParseOptions
from ._pipeline.api import parse
from ._pipeline.render import Format, render
from ._pipeline.source import Source

__version__ = PARSER_VERSION

__all__ = [
    "parse",
    "Source",
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
    "Issue",
    "Severity",
    "render",
    "Format",
    "PazufaError",
    "PdfOpenError",
    "OcrUnavailableError",
    "StepError",
    "UnknownFormatError",
    "SchemaVersionError",
]
