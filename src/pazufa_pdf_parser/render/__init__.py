"""Output renderers and their registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..errors import UnknownFormatError
from ..model import Document

RenderFunc = Callable[[Document], str]


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


def render(doc: Document, fmt: str) -> str:
    return get_renderer(fmt).func(doc)


from .html import render_html  # noqa: E402
from .json_ import render_json  # noqa: E402
from .legalxml import render_legalxml  # noqa: E402
from .text import render_raw, render_txt  # noqa: E402

register_renderer(
    "raw",
    render_raw,
    "raw.txt",
    "text/plain",
    "every extracted text piece in reading order, unsanitized, incl. headers/footers",
)
register_renderer("txt", render_txt, "txt", "text/plain", "sanitized full text without page furniture and artifacts")
register_renderer(
    "html", render_html, "html", "text/html", "lightweight structured HTML preserving columns and headings"
)
register_renderer(
    "legalxml", render_legalxml, "akn.xml", "application/akn+xml", "Akoma Ntoso 3.0 (OASIS LegalDocML) XML"
)
register_renderer(
    "json",
    render_json,
    "json",
    "application/json",
    "structured information (classification, fields, entities, structure)",
)

__all__ = ["Renderer", "register_renderer", "get_renderer", "available_formats", "render"]
