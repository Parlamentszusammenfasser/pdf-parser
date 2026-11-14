"""pazufa_pdf_parser - robust extraction of structured information and clean text from PDF documents.

Quick start::

    from pazufa_pdf_parser import parse, render

    doc = parse("letter.pdf")                 # OCR is used automatically for scans
    print(doc.classification.doc_type)        # e.g. DocType.LETTER
    print(doc.fields["letter"]["recipient"])  # structured fields
    print(render(doc, "txt"))                 # sanitized text; also: raw, html, legalxml, json
"""

from .api import convert, parse, render
from .classify import Classifier, Rule
from .errors import OcrUnavailableError, PazufaError, PdfOpenError, StepError, UnknownFormatError
from .model import (
    BBox,
    Block,
    BlockKind,
    Classification,
    DocType,
    Document,
    LegalNode,
    Line,
    Page,
    PageSource,
    Region,
    RegionKind,
    Speech,
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
    "Classifier",
    "Rule",
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
    "DocType",
    "Classification",
    "LegalNode",
    "Speech",
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
