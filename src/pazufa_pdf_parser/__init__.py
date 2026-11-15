"""pazufa_pdf_parser - robust extraction of clean text and layout from PDF documents.

Quick start::

    from pazufa_pdf_parser import parse, render

    doc = parse("letter.pdf")   # OCR is used automatically for scans
    print(render(doc, "txt"))   # sanitized text; also: raw, html, json
"""

from .api import convert, parse, render
from .errors import OcrUnavailableError, PazufaError, PdfOpenError, StepError, UnknownFormatError
from .model import (
    BBox,
    Block,
    BlockKind,
    Document,
    Line,
    Page,
    PageSource,
    Region,
    RegionKind,
    Word,
)
from .options import OcrMode, ParseOptions
from .pipeline import Context, FuncStep, Pipeline, Step, step
from .render import available_formats, register_renderer

__version__ = "0.1.0"

__all__ = [
    "parse",
    "render",
    "convert",
    "available_formats",
    "register_renderer",
    "ParseOptions",
    "OcrMode",
    "Pipeline",
    "Step",
    "FuncStep",
    "step",
    "Context",
    "Document",
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
