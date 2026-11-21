"""Pipeline of steps: extract -> layout -> garbled -> furniture -> page_numbers -> sanitize -> flow.

A pipeline is an ordered list of :class:`Step` objects. Steps never see each
other directly: they communicate through the :class:`Document` held by the
:class:`Context`.

Failures of non-critical steps are recorded as issues on the document and the
pipeline continues; with ``ParseOptions(strict=True)`` they, and the first issue
of severity ERROR, raise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable

from .._errors import PazufaError, StepError
from .._options import ParseOptions
from .extract import MAX_GARBAGE_RATIO, extract_pages
from .flow import merge_flow
from .layout import MIN_WORD_CONFIDENCE, analyze_layout
from .layout.footers import refine_footers
from .layout.furniture import assign_printed_pages
from .model import Document, Severity
from .sanitize import drop_garbled, sanitize_block
from .source import OpenedPdf, Source, open_pdf


@dataclass
class Context:
    doc: Document
    options: ParseOptions
    opened: OpenedPdf | None = None


@runtime_checkable
class Step(Protocol):
    name: str

    def run(self, ctx: Context) -> None: ...


@dataclass
class FuncStep:
    """A step wrapping a function."""

    name: str
    func: Callable[[Context], None]
    critical: bool = False  # failure aborts the pipeline (the document is unusable)

    def run(self, ctx: Context) -> None:
        self.func(ctx)


def step(name: str, *, critical: bool = False) -> Callable[[Callable[[Context], None]], FuncStep]:
    """Decorator turning a function into a :class:`FuncStep`."""

    def wrap(fn: Callable[[Context], None]) -> FuncStep:
        return FuncStep(name, fn, critical)

    return wrap


@step("extract", critical=True)
def extract_step(ctx: Context) -> None:
    if ctx.opened is None:
        raise RuntimeError("extract needs an opened PDF; run the pipeline via Pipeline.run")
    ctx.doc.pages = extract_pages(ctx.opened, ctx.options, ctx.doc)


@step("layout", critical=True)
def layout_step(ctx: Context) -> None:
    analyze_layout(ctx.doc.pages, ctx.options, ctx.doc)


@step("garbled")
def garbled_step(ctx: Context) -> None:
    """Move text in garbled fonts, on pages whose text layer OCR did not replace, to noise."""
    if not ctx.options.drop_garbled_text:
        return
    for page in ctx.doc.pages:
        if n := drop_garbled(page, MAX_GARBAGE_RATIO):
            msg = f"{n} block(s) in a garbled font moved to noise"
            ctx.doc.issue(Severity.INFO, "garbled", "garbled_dropped", msg, page.number)


@step("furniture")
def furniture_step(ctx: Context) -> None:
    """Find page footers the repetition-based detection in ``layout`` missed:
    first-page-only footers, footers of single-page documents, OCR-varying
    logos; separate footnotes from the running text."""
    ctx.doc.stats["footer_blocks_moved"] = refine_footers(ctx.doc)


@step("page_numbers")
def page_numbers_step(ctx: Context) -> None:
    """Read the number printed on each page from its header, footer and page-number lines. A number
    printed beside other text ("Bayerisches<tab>177") is first split off into a page-number block."""
    assign_printed_pages(ctx.doc.pages)


@step("sanitize")
def sanitize_step(ctx: Context) -> None:
    for page in ctx.doc.pages:
        for b in page.all_blocks:
            b.text = sanitize_block(b, MIN_WORD_CONFIDENCE)


@step("flow")
def flow_step(ctx: Context) -> None:
    """Re-join paragraphs split by page/column breaks (after furniture is removed)."""
    ctx.doc.stats["flow_joins"] = merge_flow(ctx.doc)


DEFAULT_STEPS: list[Step] = [
    extract_step,
    layout_step,
    garbled_step,
    furniture_step,
    page_numbers_step,
    sanitize_step,
    flow_step,
]


class Pipeline:
    def __init__(self, steps: Iterable[Step] | None = None):
        self.steps: list[Step] = list(steps if steps is not None else DEFAULT_STEPS)

    # ---- customisation
    def names(self) -> list[str]:
        return [s.name for s in self.steps]

    def _index(self, name: str) -> int:
        for i, s in enumerate(self.steps):
            if s.name == name:
                return i
        raise KeyError(f"no step named {name!r}; steps: {self.names()}")

    def insert_after(self, name: str, new: Step) -> Pipeline:
        self.steps.insert(self._index(name) + 1, new)
        return self

    def insert_before(self, name: str, new: Step) -> Pipeline:
        self.steps.insert(self._index(name), new)
        return self

    def replace(self, name: str, new: Step) -> Pipeline:
        self.steps[self._index(name)] = new
        return self

    def remove(self, name: str) -> Pipeline:
        del self.steps[self._index(name)]
        return self

    def append(self, new: Step) -> Pipeline:
        self.steps.append(new)
        return self

    # ---- execution
    def run(self, src: Source, options: ParseOptions | None = None) -> Document:
        options = options or ParseOptions()
        t0 = time.perf_counter()
        opened = open_pdf(src, options.password)
        doc = Document(source=opened.name, sha256=opened.sha256, pdf_info=dict(opened.info), strict=options.strict)
        ctx = Context(doc=doc, options=options, opened=opened)
        try:
            self.run_context(ctx)
        finally:
            opened.close()
            ctx.opened = None
        doc.timings["total"] = round(time.perf_counter() - t0, 3)
        return doc

    def run_context(self, ctx: Context) -> None:
        for s in self.steps:
            t = time.perf_counter()
            try:
                s.run(ctx)
            except Exception as e:  # noqa: BLE001
                if ctx.options.strict or getattr(s, "critical", False):
                    if isinstance(e, PazufaError):  # callers catch e.g. OcrUnavailableError by its own type
                        raise
                    raise StepError(s.name, e) from e
                ctx.doc.issue(Severity.ERROR, s.name, "step_failed", f"{type(e).__name__}: {e}")
            finally:
                ctx.doc.timings[s.name] = round(time.perf_counter() - t, 4)
