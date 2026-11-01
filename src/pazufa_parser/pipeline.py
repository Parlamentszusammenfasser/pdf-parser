"""Pipeline of steps with classification-based dispatch.

A pipeline is an ordered list of :class:`Step` objects. Each step decides via
``applies(ctx)`` whether it runs; logical steps typically declare the document
types they handle, so after the ``classify`` step only the relevant
extractors are dispatched. Steps never see each other directly: they
communicate through the :class:`Document` held by the :class:`Context`.

Failures of non-critical steps are recorded as issues on the document and the
pipeline continues; with ``ParseOptions(strict=True)`` they are re-raised.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from .classify import Classifier
from .errors import StepError
from .extract import extract_pages
from .fields import (
    extract_contract_fields,
    extract_court_fields,
    extract_email_fields,
    extract_entities,
    extract_legal_structure,
    extract_letter_fields,
    extract_print_fields,
    extract_protocol,
    find_dates,
    synopsis_columns,
)
from .fields.legal import find_law_span
from .layout import analyze_layout
from .layout.footers import refine_footers
from .model import Block, BlockKind, DocType, Document, RegionKind, Severity
from .options import ParseOptions
from .sanitize import is_line_structured, join_hyphenated, sanitize_block
from .source import OpenedPdf, Source, open_pdf


@dataclass
class Context:
    doc: Document
    options: ParseOptions
    opened: OpenedPdf | None = None
    classifier: Classifier = field(default_factory=Classifier)
    scratch: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Step(Protocol):
    name: str

    def applies(self, ctx: Context) -> bool: ...

    def run(self, ctx: Context) -> None: ...


@dataclass
class FuncStep:
    """A step wrapping a function, optionally restricted to document types."""

    name: str
    func: Callable[[Context], None]
    doc_types: frozenset[DocType] | None = None
    when: Callable[[Context], bool] | None = None
    critical: bool = False  # failure aborts the pipeline (the document is unusable)

    def applies(self, ctx: Context) -> bool:
        if self.doc_types is not None and ctx.doc.doc_type not in self.doc_types:
            return False
        return self.when is None or bool(self.when(ctx))

    def run(self, ctx: Context) -> None:
        self.func(ctx)


def step(
    name: str,
    *,
    doc_types: Iterable[DocType] | None = None,
    when: Callable[[Context], bool] | None = None,
    critical: bool = False,
) -> Callable[[Callable[[Context], None]], FuncStep]:
    """Decorator turning a function into a :class:`FuncStep`."""

    def wrap(fn: Callable[[Context], None]) -> FuncStep:
        return FuncStep(name, fn, frozenset(doc_types) if doc_types is not None else None, when, critical)

    return wrap


# --------------------------------------------------------------------------- physical stage


@step("extract", critical=True)
def extract_step(ctx: Context) -> None:
    assert ctx.opened is not None
    ctx.doc.pages = extract_pages(ctx.opened, ctx.options, ctx.doc)


@step("layout", critical=True)
def layout_step(ctx: Context) -> None:
    analyze_layout(ctx.doc.pages, ctx.options, ctx.doc)


_SENTENCE_END = tuple(".!?:;)“\"»…")
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
                prose = not same_region or (prev.bbox.width >= 0.5 * page_w and not is_line_structured(prev.text.split("\n")))
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


# --------------------------------------------------------------------------- logical stage


@step("classify")
def classify_step(ctx: Context) -> None:
    ctx.doc.classification = ctx.classifier.classify(ctx.doc)


@step("entities")
def entities_step(ctx: Context) -> None:
    text = "\n".join(b.text for p in ctx.doc.pages for b in p.all_blocks if b.text and (b.kind.is_body or b.kind.is_furniture))
    ctx.doc.entities = extract_entities(text)


@step("email", doc_types=[DocType.EMAIL])
def email_step(ctx: Context) -> None:
    fields = extract_email_fields(ctx.doc)
    body = [b for b in ctx.doc.body_blocks if "email_header" not in b.labels]
    letter = extract_letter_fields(ctx.doc, body, closing="first")
    for k in ("salutation", "closing", "signatory", "attachments", "attached_letter"):
        if k in letter and k not in fields:
            fields[k] = letter[k]
    ctx.doc.fields["email"] = fields


@step("letter", doc_types=[DocType.LETTER])
def letter_step(ctx: Context) -> None:
    ctx.doc.fields["letter"] = extract_letter_fields(ctx.doc)


@step("parliamentary_print", doc_types=[DocType.PARLIAMENTARY_PRINT])
def print_step(ctx: Context) -> None:
    ctx.doc.fields["print"] = extract_print_fields(ctx.doc)


@step("plenary_protocol", doc_types=[DocType.PLENARY_PROTOCOL])
def protocol_step(ctx: Context) -> None:
    fields, speeches = extract_protocol(ctx.doc)
    ctx.doc.fields["protocol"] = fields
    ctx.doc.speeches = speeches


@step("court_decision", doc_types=[DocType.COURT_DECISION])
def court_step(ctx: Context) -> None:
    ctx.doc.fields["court"] = extract_court_fields(ctx.doc)


@step("contract", doc_types=[DocType.CONTRACT])
def contract_step(ctx: Context) -> None:
    ctx.doc.fields["contract"] = extract_contract_fields(ctx.doc)


def _has_synopsis(ctx: Context) -> bool:
    return bool(ctx.doc.classification.features.get("has_synopsis"))


@step("synopsis", when=_has_synopsis)
def synopsis_step(ctx: Context) -> None:
    syn = synopsis_columns(ctx.doc)
    ctx.doc.synopsis = [
        {"pages": s["pages"], "left_label": s["left_label"], "right_label": s["right_label"], "left": s["left"], "right": s["right"]}
        for s in syn
    ]


_LEGAL_TYPES = [DocType.PARLIAMENTARY_PRINT, DocType.STATUTE, DocType.CONTRACT, DocType.GENERIC]


@step("legal_structure", doc_types=_LEGAL_TYPES)
def legal_step(ctx: Context) -> None:
    ctx.doc.legal = extract_legal_structure(ctx.doc)
    if ctx.doc.legal:
        # label the blocks of the normative text so renderers can separate them
        syn = _synopsis_block_ids(ctx.doc)
        blocks = [b for b in ctx.doc.body_blocks if id(b) not in syn]
        span = find_law_span(blocks)
        if span:
            for b in blocks[span[0] : span[1]]:
                b.labels.add("legal")


_TITLE_SKIP_RE = re.compile(r"^(\d+\.\s*Wahlperiode|Drucksache|Seite\s*\d|Protokollauszug)", re.I)


@step("summary")
def summary_step(ctx: Context) -> None:
    """Document-level fields: title, date, language, outline."""
    doc = ctx.doc
    f = doc.fields
    cls = doc.classification
    title = None
    for key, sub in (("print", "title"), ("email", "subject_clean"), ("letter", "subject"), ("protocol", "topic"), ("contract", "title"), ("court", "subject")):
        v = f.get(key, {}).get(sub) if isinstance(f.get(key), dict) else None
        if v:
            title = v
            break
    if title is None:
        pdf_title = (doc.pdf_info.get("Title") or "").strip()
        if len(pdf_title) > 3:
            title = pdf_title
    if title is None:
        heads = [
            b
            for b in doc.body_blocks[:15]
            if b.kind is BlockKind.HEADING
            and b.text
            and not _TITLE_SKIP_RE.match(b.text)
            and b.bbox.y0 < doc.pages[b.page - 1].height * 0.85  # not a footer logo / slogan
        ]
        if heads:
            best = min(heads, key=lambda b: (b.level, b.page, b.bbox.y0))
            title = " ".join(best.text.split())
    if title:
        f["title"] = title
    date = None
    for key in ("print", "letter", "email", "protocol", "court"):
        v = f.get(key, {}).get("date") if isinstance(f.get(key), dict) else None
        if v:
            date = v
            break
    if date is None:
        first = doc.pages[0] if doc.pages else None
        if first is not None:
            d = find_dates("\n".join(b.text for b in first.all_blocks if b.text)[:1500])
            if d:
                date = d[0]["iso"]
    if date:
        f["date"] = date
    f["language"] = cls.features.get("language", "und")
    outline = [
        {"level": b.level, "text": " ".join(b.text.split()), "page": b.page}
        for b in doc.body_blocks
        if b.kind is BlockKind.HEADING and b.text
    ]
    if outline:
        f["outline"] = outline
    doc.stats.update(
        pages=len(doc.pages),
        ocr_pages=cls.features.get("ocr_pages", 0),
        columns_regions=sum(1 for p in doc.pages if p.layout for r in p.layout.iter_regions() if r.kind is RegionKind.COLUMNS),
        body_blocks=len(doc.body_blocks),
        furniture_blocks=sum(len(p.furniture) for p in doc.pages),
    )


DEFAULT_STEPS: list[Step] = [
    extract_step,
    layout_step,
    furniture_step,
    sanitize_step,
    flow_step,
    classify_step,
    entities_step,
    email_step,
    letter_step,
    print_step,
    protocol_step,
    court_step,
    contract_step,
    synopsis_step,
    legal_step,
    summary_step,
]


class Pipeline:
    def __init__(self, steps: Iterable[Step] | None = None, classifier: Classifier | None = None):
        self.steps: list[Step] = list(steps if steps is not None else DEFAULT_STEPS)
        self.classifier = classifier or Classifier()

    @classmethod
    def default(cls) -> Pipeline:
        return cls()

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
        ctx = Context(doc=doc, options=options, opened=opened, classifier=self.classifier)
        try:
            self.run_context(ctx)
        finally:
            opened.close()
            ctx.opened = None
        doc.timings["total"] = round(time.perf_counter() - t0, 3)
        return doc

    def run_context(self, ctx: Context) -> None:
        for s in self.steps:
            try:
                if not s.applies(ctx):
                    continue
            except Exception as e:  # noqa: BLE001
                ctx.doc.issue(Severity.ERROR, s.name, f"applies() failed: {e!r}")
                if ctx.options.strict:
                    raise StepError(s.name, e) from e
                continue
            t = time.perf_counter()
            try:
                s.run(ctx)
            except Exception as e:  # noqa: BLE001
                ctx.doc.issue(Severity.ERROR, s.name, f"{type(e).__name__}: {e}")
                if ctx.options.strict or getattr(s, "critical", False):
                    raise StepError(s.name, e) from e
            finally:
                ctx.doc.timings[s.name] = round(time.perf_counter() - t, 4)
