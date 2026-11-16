"""pazufa_pdf_parser - robust extraction of clean text and layout from PDF documents.

Quick start::

    from pazufa_pdf_parser import parse, render

    doc = parse("letter.pdf")   # OCR is used automatically for scans
    print(doc.text())           # sanitized body text; render(doc, "html") for other formats
"""

from .api import convert, parse, render
from .document import PARSER_VERSION, Block, Page, PdfDocument
from .errors import OcrUnavailableError, PazufaError, PdfOpenError, StepError, UnknownFormatError
from .model import (
    BBox,
    BlockKind,
    Document,
    Line,
    PageSource,
    Region,
    RegionKind,
    Word,
)
from .options import Ocr, OcrMode, ParseOptions
from .pipeline import Context, FuncStep, Pipeline, Step, step
from .render import available_formats, register_renderer

__version__ = PARSER_VERSION

__all__ = [
    "parse",
    "render",
    "convert",
    "available_formats",
    "register_renderer",
    "ParseOptions",
    "OcrMode",
    "Ocr",
    "Pipeline",
    "Step",
    "FuncStep",
    "step",
    "Context",
    "Document",
    "PdfDocument",
    "Page",
    "Block",
    "BlockKind",
    "Line",
    "Word",
    "BBox",
    "Region",
    "RegionKind",
    "PageSource",
    "PazufaError",
    "PdfOpenError",
    "OcrUnavailableError",
    "StepError",
    "UnknownFormatError",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    from .cli import main as _main

    return _main(argv)
