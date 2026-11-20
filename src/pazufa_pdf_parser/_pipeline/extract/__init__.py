"""Physical extraction: text layer and/or OCR per page, orientation normalisation."""

from __future__ import annotations

import contextlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..._errors import OcrUnavailableError
from ..._options import OcrMode, ParseOptions
from ..model import BBox, Document, Page, PageSource, Severity, Word
from ..source import PDFIUM_LOCK, OpenedPdf
from .ocr import OcrResult, ocr_image, resolve_languages
from .pdf import extract_page_words, image_coverage, page_has_vector_glyphs

__all__ = ["extract_pages", "decide_ocr", "rotate_words"]


@dataclass(slots=True)
class _Probe:
    index: int
    page: Page
    want_ocr: bool
    merge: bool  # keep text layer and add OCR words that do not overlap it
    reason: str


def _meaningful_chars(words: list[Word]) -> int:
    return sum(sum(ch.isalnum() for ch in w.text) for w in words)


def decide_ocr(stats: dict, words: list[Word], options: ParseOptions) -> tuple[bool, bool, str]:
    """Decide whether a page needs OCR. Returns (ocr, merge_with_text_layer, reason)."""
    if options.ocr is OcrMode.NEVER:
        return False, False, "ocr disabled"
    if options.ocr is OcrMode.ALWAYS:
        return True, False, "ocr forced"
    meaningful = _meaningful_chars(words)
    cover = stats.get("image_coverage", 0.0)
    if stats.get("garbage_ratio", 0.0) > options.max_garbage_ratio and stats.get("chars", 0) >= 10:
        return True, False, f"text layer garbled ({stats['garbage_ratio']:.0%} garbage)"
    if meaningful < options.min_text_chars:
        if cover > 0.02 or stats.get("paths", 0) > 50:
            return True, False, "no usable text layer"
        return False, False, "blank page"
    if cover > 0.4 and meaningful < 400:
        return True, True, "large image with sparse text layer"
    return False, False, "text layer ok"


def rotate_words(words: list[Word], width: float, height: float, ccw: int) -> tuple[float, float]:
    """Rotate word boxes in place by ``ccw`` degrees counter-clockwise (visual). Returns new size."""
    ccw %= 360
    if ccw == 0:
        return width, height
    for w in words:
        b = w.bbox
        pts = [(b.x0, b.y0), (b.x1, b.y1)]
        if ccw == 90:
            pts = [(y, width - x) for x, y in pts]
        elif ccw == 180:
            pts = [(width - x, height - y) for x, y in pts]
        elif ccw == 270:
            pts = [(height - y, x) for x, y in pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w.bbox = BBox(min(xs), min(ys), max(xs), max(ys))
        w.angle = (w.angle + ccw) % 360
    return (height, width) if ccw in (90, 270) else (width, height)


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
    page.width, page.height = rotate_words(page.words, page.width, page.height, (360 - angle) % 360)
    page.stats["orientation_corrected"] = (360 - angle) % 360


def extract_pages(opened: OpenedPdf, options: ParseOptions, doc: Document) -> list[Page]:
    n = len(opened.pdf)
    first = max(1, options.first_page or 1)
    last = min(n, options.last_page or n)
    probes: list[_Probe] = []
    with PDFIUM_LOCK:
        for idx in range(first - 1, last):
            try:
                pg = opened.pdf[idx]
            except Exception as e:  # damaged page tree
                doc.issue(Severity.ERROR, "extract", f"cannot load page: {e}", idx + 1)
                probes.append(
                    _Probe(idx, Page(idx + 1, 595.0, 842.0, source=PageSource.EMPTY), False, False, "unloadable")
                )
                continue
            w, h = pg.get_size()
            page = Page(number=idx + 1, width=w, height=h, rotation=pg.get_rotation())
            words: list[Word] = []
            stats: dict = {}
            try:
                pt = extract_page_words(pg)
                words, stats = pt.words, pt.stats
            except Exception as e:
                doc.issue(Severity.WARNING, "extract", f"text layer extraction failed: {e}", page.number)
                stats = {"chars": 0, "garbage_ratio": 0.0}
            stats["image_coverage"] = round(image_coverage(pg), 3)
            if _meaningful_chars(words) < options.min_text_chars:
                stats["paths"] = page_has_vector_glyphs(pg)
            page.words = words
            page.stats.update(stats)
            want, merge, reason = decide_ocr(stats, words, options)
            page.stats["ocr_reason"] = reason
            if not want:
                page.source = PageSource.TEXT if words else PageSource.EMPTY
            probes.append(_Probe(idx, page, want, merge, reason))
            with contextlib.suppress(Exception):
                pg.close()

    todo = [p for p in probes if p.want_ocr]
    if todo:
        _run_ocr(opened, options, doc, todo)

    pages = [p.page for p in probes]
    for page in pages:
        if page.source is not PageSource.OCR:
            _normalize_orientation(page)
    return pages


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
        p.page.stats["ocr_reason"] += f"; not OCRed: {why}"
        if not p.page.words:
            p.page.source = PageSource.EMPTY


def _run_ocr(opened: OpenedPdf, options: ParseOptions, doc: Document, todo: list[_Probe]) -> None:
    engine = options.ocr_engine
    severity = Severity.ERROR if options.ocr is OcrMode.ALWAYS else Severity.WARNING
    limit = options.max_ocr_pages
    if limit is not None and len(todo) > limit:
        doc.issue(severity, "ocr", f"{len(todo)} page(s) need OCR, over the limit of {limit}; left without OCR")
        _leave_without_ocr(todo, f"{len(todo)} pages need OCR, over max_ocr_pages={limit}")
        return
    try:
        lang, missing = resolve_languages(engine.languages, engine.tesseract_cmd)
    except OcrUnavailableError as e:
        doc.issue(severity, "ocr", f"{e}; {len(todo)} page(s) left without OCR")
        _leave_without_ocr(todo, "tesseract unavailable")
        if options.strict:
            raise
        return
    if missing:
        doc.issue(Severity.WARNING, "ocr", f"tesseract languages not installed: {', '.join(missing)}; using {lang}")

    def work(p: _Probe) -> tuple[_Probe, OcrResult | None, Exception | None]:
        try:
            # the slot also covers rendering: a 300 dpi page image is ~25 MB, so waiting pages stay unrendered
            with engine._slots:
                with PDFIUM_LOCK:
                    pg = opened.pdf[p.index]
                    img = pg.render(scale=engine.dpi / 72.0, may_draw_forms=True).to_pil()
                    pg.close()
                result = ocr_image(
                    img,
                    engine.dpi,
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
                doc.issue(Severity.ERROR, "ocr", f"OCR failed: {err}", page.number)
                if options.strict and err is not None:
                    raise err
                _leave_without_ocr([p], "OCR failed")
                continue
            page.stats.update(res.stats)
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
                page.stats["orientation_corrected"] = res.rotation
                doc.issue(Severity.INFO, "ocr", f"page rotated by {res.rotation}° for OCR", page.number)
