"""High-level library API."""

from __future__ import annotations

from .document import PdfDocument, build_document
from .options import ParseOptions
from .pipeline import Pipeline
from .render import render as _render
from .source import Source

_default_pipeline: Pipeline | None = None


def _pipeline() -> Pipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = Pipeline.default()
    return _default_pipeline


def parse(
    src: Source, options: ParseOptions | None = None, *, pipeline: Pipeline | None = None, **option_overrides
) -> PdfDocument:
    """Parse a PDF (path, bytes or binary file object) into a :class:`PdfDocument`.

    Keyword arguments override fields of ``options``, e.g. ``parse(path, ocr="never")``.
    """
    opts = options or ParseOptions()
    if option_overrides:
        if "ocr" in option_overrides and isinstance(option_overrides["ocr"], str):
            from .options import OcrMode

            option_overrides["ocr"] = OcrMode(option_overrides["ocr"])
        if "languages" in option_overrides and isinstance(option_overrides["languages"], str):
            option_overrides["languages"] = tuple(option_overrides["languages"].replace(",", "+").split("+"))
        opts = opts.with_(**option_overrides)
    return build_document((pipeline or _pipeline()).run(src, opts))


def render(doc: PdfDocument, fmt: str) -> str:
    """Render a parsed document to one of the registered formats (see :func:`available_formats`)."""
    return _render(doc, fmt)


def convert(src: Source, fmt: str = "txt", options: ParseOptions | None = None, **option_overrides) -> str:
    """Parse and render in one call."""
    return render(parse(src, options, **option_overrides), fmt)
