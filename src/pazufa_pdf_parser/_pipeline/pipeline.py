"""Pipeline of steps: extract -> layout -> furniture -> sanitize -> flow.

A pipeline is an ordered list of :class:`Step` objects. Steps never see each
other directly: they communicate through the :class:`Document` held by the
:class:`Context`.

Failures of non-critical steps are recorded as issues on the document and the
pipeline continues; with ``ParseOptions(strict=True)`` they are re-raised.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable

from .._errors import PazufaError, StepError
from .._options import ParseOptions
from .extract import extract_pages
from .layout import analyze_layout
from .layout.footers import refine_footers
from .model import Block, BlockKind, Document, Severity
from .sanitize import is_line_structured, join_hyphenated, sanitize_block
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


_SENTENCE_END = tuple('.!?:;)“"»…')
_SALUTATION_RE = re.compile(r"^\s*(Sehr geehrte[rs]?|Liebe[rs]?|Hallo|Guten Tag|Dear)\b", re.I)


def _synopsis_block_ids(doc: Document) -> set[int]:
    ids: set[int] = set()
    for p in doc.pages:
        if p.layout is None:
            continue
        for r in p.layout.iter_regions():
            if r.synopsis:
                ids.update(id(b) for b in r.iter_blocks())
    return ids


def merge_flow(doc: Document) -> int:
    """Join paragraphs split by page/column breaks or spurious layout splits.

    Across regions/pages a join requires similar, reasonably wide blocks (never a
    sidebar); inside a region only clear continuations (next block starts lower-case)
    are joined.
    """
    skip = _synopsis_block_ids(doc)
    prev: Block | None = None
    joins = 0
    for b in doc.body_blocks:
        if not b.text or b.kind is BlockKind.FOOTNOTE:
            continue  # footnotes sit between a page's last and the next page's first paragraph
        if (
            prev is not None
            and id(b) not in skip
            and id(prev) not in skip
            and prev.kind in (BlockKind.PARAGRAPH, BlockKind.LIST_ITEM)
            and b.kind is BlockKind.PARAGRAPH
        ):
            same_region = prev.page == b.page and prev.region == b.region
            page_w = doc.pages[b.page - 1].width or 1.0
            compatible = same_region or (
                min(prev.bbox.width, b.bbox.width) >= 0.35 * page_w
                and min(prev.bbox.width, b.bbox.width) / max(prev.bbox.width, b.bbox.width, 1.0) >= 0.6
            )
            joined = None
            if compatible and not _SALUTATION_RE.match(prev.text):
                if not same_region:
                    joined = join_hyphenated(prev.text, b.text)
                # inside one region only prose continues ("- Kläger -" / "gegen" must stay apart)
                prose = not same_region or (
                    prev.bbox.width >= 0.5 * page_w and not is_line_structured(prev.text.split("\n"))
                )
                if joined is None and prose and not prev.text.rstrip().endswith(_SENTENCE_END) and b.text[:1].islower():
                    joined = prev.text.rstrip() + " " + b.text.lstrip()
            if joined is not None:
                prev.text = joined
                b.text = ""
                b.labels.add("merged_into_previous")
                joins += 1
                continue
        prev = b
    return joins


@step("furniture")
def furniture_step(ctx: Context) -> None:
    """Find page footers the repetition-based detection in ``layout`` missed:
    first-page-only footers, footers of single-page documents, OCR-varying
    logos; separate footnotes from the running text."""
    ctx.doc.stats["footer_blocks_moved"] = refine_footers(ctx.doc)


@step("sanitize")
def sanitize_step(ctx: Context) -> None:
    min_conf = ctx.options.min_word_confidence
    for page in ctx.doc.pages:
        for b in page.all_blocks:
            b.text = sanitize_block(b, min_conf)


@step("flow")
def flow_step(ctx: Context) -> None:
    """Re-join paragraphs split by page/column breaks (after furniture is removed)."""
    ctx.doc.stats["flow_joins"] = merge_flow(ctx.doc)


DEFAULT_STEPS: list[Step] = [
    extract_step,
    layout_step,
    furniture_step,
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
        doc = Document(source=opened.name, sha256=opened.sha256, pdf_info=dict(opened.info))
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
                ctx.doc.issue(Severity.ERROR, s.name, f"{type(e).__name__}: {e}")
                if ctx.options.strict or getattr(s, "critical", False):
                    if isinstance(e, PazufaError):  # callers catch e.g. OcrUnavailableError by its own type
                        raise
                    raise StepError(s.name, e) from e
            finally:
                ctx.doc.timings[s.name] = round(time.perf_counter() - t, 4)
