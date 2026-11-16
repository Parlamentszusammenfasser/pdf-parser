"""Output renderers and their registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ...document import PdfDocument
from ...errors import UnknownFormatError

RenderFunc = Callable[[PdfDocument], str]


@dataclass(frozen=True)
class Renderer:
    name: str
    func: RenderFunc
    extension: str
    media_type: str
    description: str = ""


_REGISTRY: dict[str, Renderer] = {}


def register_renderer(
    name: str, func: RenderFunc, extension: str, media_type: str = "text/plain", description: str = ""
) -> None:
    """Register (or replace) an output format."""
    _REGISTRY[name.lower()] = Renderer(name.lower(), func, extension, media_type, description)


def get_renderer(name: str) -> Renderer:
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        raise UnknownFormatError(
            f"unknown output format {name!r}; available: {', '.join(available_formats())}"
        ) from None


def available_formats() -> list[str]:
    return sorted(_REGISTRY)


def render(doc: PdfDocument, fmt: str) -> str:
    """Render a parsed document as "txt", "raw", "html" or "json"; raises UnknownFormatError otherwise."""
    return get_renderer(fmt).func(doc)


from .html import render_html  # noqa: E402
from .text import render_raw, render_txt  # noqa: E402

register_renderer(
    "raw",
    render_raw,
    "raw.txt",
    "text/plain",
    "every block in reading order incl. headers, footers and margin notes; text sanitized like txt",
)
register_renderer("txt", render_txt, "txt", "text/plain", "sanitized full text without page furniture and artifacts")
register_renderer("html", render_html, "html", "text/html", "headings, paragraphs and lists in reading order")
register_renderer(
    "json", lambda d: d.to_json() + "\n", "json", "application/json", "pages and blocks with geometry, metadata, report"
)

__all__ = ["Renderer", "register_renderer", "get_renderer", "available_formats", "render"]
