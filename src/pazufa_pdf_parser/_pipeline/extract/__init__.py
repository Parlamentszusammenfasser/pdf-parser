"""Physical extraction: text layer and/or OCR per page, orientation normalisation."""

from __future__ import annotations

import contextlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..._errors import OcrUnavailableError
from ..._options import OcrMode, ParseOptions
from ..model import Document, Page, PageSource, Severity, Word, rotate_words
from ..source import PDFIUM_LOCK, OpenedPdf
from .ocr import OcrResult, ocr_image, resolve_languages
from .pdf import extract_page_words, image_coverage, page_has_vector_glyphs, page_rules

__all__ = ["extract_pages", "MAX_GARBAGE_RATIO"]

MIN_TEXT_CHARS = 25  # a page with fewer letters and digits has no text layer to speak of
MAX_GARBAGE_RATIO = 0.15  # above this share of unmapped characters a text layer, or a font on it, is garbled


@dataclass(slots=True)
class _Probe:
    index: int
    page: Page
    want_ocr: bool
    merge: bool  # keep text layer and add OCR words that do not overlap it


def _meaningful_chars(words: list[Word]) -> int:
    return sum(sum(ch.isalnum() for ch in w.text) for w in words)


def _text_layer(stats: dict, words: list[Word]) -> tuple[bool, bool, str]:
    """Whether the text layer needs OCR, and whether to merge OCR words into it. Returns
    (needs_ocr, merge_with_text_layer, reason)."""
    meaningful = _meaningful_chars(words)
    cover = stats.get("image_coverage", 0.0)
    if stats.get("garbage_ratio", 0.0) > MAX_GARBAGE_RATIO and stats.get("chars", 0) >= 10:
        return True, False, f"text layer garbled ({stats['garbage_ratio']:.0%} garbage)"
    if meaningful < MIN_TEXT_CHARS:
        if cover > 0.02 or stats.get("paths", 0) > 50:
            return True, False, "no usable text layer"
        return False, False, "blank page"
    if cover > 0.4 and meaningful < 400:
        return True, True, "large image with sparse text layer"
    return False, False, "text layer ok"


def _decide_ocr(mode: OcrMode, needs: bool, merge: bool, reason: str) -> tuple[bool, bool, str]:
    """Returns (ocr, merge_with_text_layer, reason)."""
    if mode is OcrMode.NEVER:
        return False, False, f"ocr disabled; {reason}"
    if mode is OcrMode.ALWAYS:
        return True, False, "ocr forced"
    return needs, merge, reason


def _normalize_orientation(page: Page) -> None:
    """If most text on a page runs in one non-upright direction, rotate the page frame."""
    counts: Counter[int] = Counter()
    for w in page.words:
        counts[w.angle] += len(w.text)
    if not counts:
        return
    angle, n = counts.most_common(1)[0]
    if angle == 0 or n < 0.6 * sum(counts.values()):
        return
    ccw = (360 - angle) % 360
    page.rules = [r.rotated(page.width, page.height, ccw) for r in page.rules]
    page.width, page.height = rotate_words(page.words, page.width, page.height, ccw)
    page.stats["orientation_corrected"] = ccw


MAX_OCR_PIXELS = 100_000_000  # 400 MB as RGBA; an A1 plan at 300 dpi has 70 million


def ocr_dpi(width: float, height: float, dpi: int) -> int:
    """The resolution to render a page of this size (in points) at for OCR: ``dpi``, or less for a huge page."""
    fit = int((MAX_OCR_PIXELS / max(width * height, 1.0)) ** 0.5 * 72)
    return max(1, min(dpi, fit))


def extract_pages(opened: OpenedPdf, options: ParseOptions, doc: Document) -> list[Page]:
    n = opened.info["page_count"]  # read under the pdfium lock when opened
    first = options.first_page or 1
    last = min(n, options.last_page or n)
    if first > n:
        doc.issue(Severity.WARNING, "extract", "page_range_empty", f"first_page {first} is beyond the last page, {n}")
    probes = [_probe(opened, idx, options, doc) for idx in range(first - 1, last)]

    todo = [p for p in probes if p.want_ocr]
    if todo:
        _run_ocr(opened, options, doc, todo)

    pages = [p.page for p in probes]
    for page in pages:
        if page.source is not PageSource.OCR:
            _normalize_orientation(page)
    return pages


def _probe(opened: OpenedPdf, idx: int, options: ParseOptions, doc: Document) -> _Probe:
    """Read one page's text layer and decide on OCR. Holds the pdfium lock for this page only, so
    parses in other threads take turns instead of waiting for the whole PDF."""
    with PDFIUM_LOCK:
        try:
            pg = opened.pdf[idx]
        except Exception as e:  # damaged page tree
            doc.issue(Severity.ERROR, "extract", "page_unloadable", f"cannot load page: {e}", idx + 1)
            page = Page(idx + 1, 595.0, 842.0, source=PageSource.EMPTY, ocr_reason="page unloadable")
            return _Probe(idx, page, False, False)
        try:
            w, h = pg.get_size()
            page = Page(number=idx + 1, width=w, height=h, rotation=pg.get_rotation())
            try:
                pt = extract_page_words(pg)
                page.words, page.stats = pt.words, pt.stats
            except Exception as e:
                doc.issue(
                    Severity.WARNING, "extract", "text_layer_failed", f"text layer extraction failed: {e}", page.number
                )
                page.stats = {"chars": 0, "garbage_ratio": 0.0}
            page.stats["image_coverage"] = round(image_coverage(pg), 3)
            page.rules = page_rules(pg)
            if _meaningful_chars(page.words) < MIN_TEXT_CHARS:
                page.stats["paths"] = page_has_vector_glyphs(pg)
        finally:
            with contextlib.suppress(Exception):
                pg.close()
    page.garbage_ratio = page.stats["garbage_ratio"]
    page.needs_ocr, merge, reason = _text_layer(page.stats, page.words)
    want, merge, page.ocr_reason = _decide_ocr(options.ocr, page.needs_ocr, merge, reason)
    if not want:
        page.source = PageSource.TEXT if page.words else PageSource.EMPTY
    return _Probe(idx, page, want, merge)


def _lone_numbers_missed(text: list[Word], ocr: list[Word]) -> list[Word]:
    """Text-layer numbers alone on their row that OCR missed: tesseract drops the lone bold page number
    of BW Drucksache annexes, while their shifted font turns its own digits into control characters."""
    # shortcut: the +29 shift also turns a lone capital M–V into a digit; restrict to the page bands if one shows up
    return [
        w
        for w in text
        if w.text.isdecimal()
        and not any(o is not w and o.bbox.y_overlap(w.bbox) > 0 for o in text)
        and not any(o.bbox.x_overlap(w.bbox) > 0 and o.bbox.y_overlap(w.bbox) > 0 for o in ocr)
    ]


def _leave_without_ocr(todo: list[_Probe], why: str) -> None:
    for p in todo:
        p.page.ocr_reason += f"; not OCRed: {why}"
        if not p.page.words:
            p.page.source = PageSource.EMPTY


def _run_ocr(opened: OpenedPdf, options: ParseOptions, doc: Document, todo: list[_Probe]) -> None:
    engine = options.ocr_engine
    severity = Severity.ERROR if options.ocr is OcrMode.ALWAYS else Severity.WARNING
    limit = options.max_ocr_pages
    if limit is not None and len(todo) > limit:
        doc.issue(
            severity, "ocr", "ocr_limit", f"{len(todo)} page(s) need OCR, over the limit of {limit}; left without OCR"
        )
        _leave_without_ocr(todo, f"{len(todo)} pages need OCR, over max_ocr_pages={limit}")
        return
    try:
        lang, missing = resolve_languages(engine.languages, engine.tesseract_cmd)
    except OcrUnavailableError as e:
        if options.strict:
            raise  # callers catch it by its own type
        doc.issue(severity, "ocr", "ocr_unavailable", f"{e}; {len(todo)} page(s) left without OCR")
        _leave_without_ocr(todo, "tesseract unavailable")
        return
    if missing:
        doc.issue(
            Severity.WARNING,
            "ocr",
            "ocr_languages_missing",
            f"tesseract languages not installed: {', '.join(missing)}; using {lang}",
        )

    def work(p: _Probe) -> tuple[_Probe, OcrResult | None, Exception | None]:
        try:
            # the slot also covers rendering: a 300 dpi page image is ~25 MB, so waiting pages stay unrendered
            with engine._slots:
                dpi = ocr_dpi(p.page.width, p.page.height, engine.dpi)
                with PDFIUM_LOCK:
                    pg = opened.pdf[p.index]
                    img = pg.render(scale=dpi / 72.0, may_draw_forms=True).to_pil()
                    pg.close()
                result = ocr_image(
                    img,
                    dpi,
                    lang,
                    detect_orientation=engine.detect_orientation,
                    cmd=engine.tesseract_cmd,
                    timeout=engine.timeout,
                )
            return p, result, None
        except Exception as e:  # noqa: BLE001 - recorded as issue
            return p, None, e

    with ThreadPoolExecutor(max_workers=engine.max_parallel) as ex:
        for p, res, err in ex.map(work, todo):
            page = p.page
            if err is not None or res is None:
                if options.strict and err is not None:
                    raise err
                doc.issue(Severity.ERROR, "ocr", "ocr_failed", f"OCR failed: {err}", page.number)
                _leave_without_ocr([p], "OCR failed")
                continue
            page.stats.update(res.stats)
            page.needs_ocr = False
            page.ocr_confidence = round(res.mean_confidence, 2)
            if (dpi := ocr_dpi(page.width, page.height, engine.dpi)) < engine.dpi:
                msg = f"page too large for {engine.dpi} dpi, OCRed at {dpi} dpi"
                doc.issue(Severity.INFO, "ocr", "ocr_dpi_lowered", msg, page.number)
            if p.merge and page.words and not res.rotation:
                kept = [
                    w
                    for w in res.words
                    if not any(w.bbox.x_overlap(t.bbox) > 0 and w.bbox.y_overlap(t.bbox) > 0 for t in page.words)
                ]
                page.words = page.words + kept
                page.stats["ocr_words_merged"] = len(kept)
                page.source = PageSource.TEXT
            else:
                page.words = res.words + ([] if res.rotation else _lone_numbers_missed(page.words, res.words))
                page.width, page.height = res.width, res.height
                page.source = PageSource.OCR if page.words else PageSource.EMPTY
            if res.rotation:
                page.rules = []  # the words now lie in the turned scan's frame
                page.stats["orientation_corrected"] = res.rotation
                doc.issue(Severity.INFO, "ocr", "ocr_rotated", f"page rotated by {res.rotation}° for OCR", page.number)
