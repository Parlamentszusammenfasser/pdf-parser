"""Output renderers and their registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from ..._document import PdfDocument
from ..._errors import UnknownFormatError

RenderFunc = Callable[[PdfDocument], str]
#: output formats of render(); a typo fails type checking, not only at runtime
Format = Literal["txt", "raw", "html", "json"]


@dataclass(frozen=True)
class Renderer:
    name: str
    func: RenderFunc
    extension: str
    description: str = ""


_REGISTRY: dict[str, Renderer] = {}


def register_renderer(name: str, func: RenderFunc, extension: str, description: str = "") -> None:
    """Register (or replace) an output format. ``render()`` and the CLI accept any registered name; for type
    checkers a new one must also be added to ``Format``."""
    _REGISTRY[name.lower()] = Renderer(name.lower(), func, extension, description)


def get_renderer(name: str) -> Renderer:
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        raise UnknownFormatError(
            f"unknown output format {name!r}; available: {', '.join(available_formats())}"
        ) from None


def available_formats() -> list[str]:
    return sorted(_REGISTRY)


def render(doc: PdfDocument, fmt: Format) -> str:
    """Render a parsed document in one of the :data:`Format` formats; raises UnknownFormatError otherwise."""
    return get_renderer(fmt).func(doc)


from .html import render_html  # noqa: E402
from .text import render_raw, render_txt  # noqa: E402

register_renderer(
    "raw",
    render_raw,
    "raw.txt",
    "every block in reading order incl. headers, footers and margin notes; text sanitized like txt",
)
register_renderer("txt", render_txt, "txt", "sanitized full text without page furniture and artifacts")
register_renderer("html", render_html, "html", "headings, paragraphs and lists in reading order")
register_renderer("json", lambda d: d.to_json() + "\n", "json", "pages and blocks with geometry, metadata, report")

__all__ = ["Format", "Renderer", "register_renderer", "get_renderer", "available_formats", "render"]
