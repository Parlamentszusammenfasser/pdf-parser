"""Layout analysis: lines, furniture, segmentation, blocks, headings."""

from __future__ import annotations

import copy
import re

from ..._options import ParseOptions
from ..model import BBox, Block, BlockKind, Document, Line, Page, Region, RegionKind, Word, rotate_words
from ..sanitize import is_ocr_noise
from .blocks import classify_headings, fill_leaves
from .furniture import detect_furniture, is_page_number
from .lines import build_lines, make_line
from .segment import Segmenter, detect_synopsis, page_body_size

__all__ = ["analyze_layout", "document_body_size", "MIN_WORD_CONFIDENCE"]

MIN_WORD_CONFIDENCE = 25.0  # OCR words below this tesseract confidence are mostly specks and stamps

_LINE_NUMBER_RE = re.compile(r"^\d{1,4}$")


def _rotated_blocks(page: Page, words: list[Word], body: BBox) -> list[Block]:
    """Rotated text, per direction, as marginal blocks of lines rebuilt in that direction's upright frame.
    On a page turned upright, lines upright on the paper beyond the ``body`` are its header, footer or page
    number instead: a sideways table keeps them in the paper's direction (BW Drs. 18/623 pp. 56-90)."""
    out: list[Block] = []
    by_angle: dict[int, list[Word]] = {}
    for w in words:
        by_angle.setdefault(w.angle, []).append(w)
    # upright on the paper is upright in user space: /Rotate turns only the view
    ccw = page.stats.get("orientation_corrected")
    paper = None if ccw is None else (ccw - page.rotation) % 360
    for angle, ws in by_angle.items():
        copies = [copy.copy(w) for w in ws]
        turn = (360 - angle) % 360
        frame = rotate_words(copies, page.width, page.height, turn)
        lines = build_lines(copies)
        if angle == paper:
            paper_body = body.rotated(page.width, page.height, turn)
            rest = []
            for ln in lines:
                if furniture := _margin_furniture(ln, paper_body, frame, angle, page.number):
                    out.append(furniture)
                else:
                    rest.append(ln)
            lines = rest
        if lines:
            bbox = BBox.enclosing(ln.bbox for ln in lines).rotated(*frame, angle)
            out.append(Block(lines=lines, bbox=bbox, page=page.number, kind=BlockKind.MARGINAL))
    return out


def _margin_furniture(line: Line, body: BBox, frame: tuple[float, float], angle: int, page: int) -> Block | None:
    """A line above or below the body (both in the paper's frame) as a header, footer or page-number block,
    turned back to view space; its words then stack vertically, so the page_numbers step never splits it."""
    if line.bbox.y1 > body.y0 and line.bbox.y0 < body.y1:
        return None
    kind = BlockKind.HEADER if line.bbox.y1 <= body.y0 else BlockKind.FOOTER
    if is_page_number(line.text):
        kind = BlockKind.PAGE_NUMBER
    rotate_words(line.words, *frame, angle)
    # shortcut: Page.all_blocks orders furniture by view y, so two stacked footer lines can swap (BY GVBl p. 193)
    line.bbox = line.bbox.rotated(*frame, angle)
    return Block(lines=[line], bbox=line.bbox, page=page, kind=kind)


def document_body_size(pages: list[Page]) -> float:
    words = [w for p in pages for b in p.blocks for ln in b.lines for w in ln.words]
    return page_body_size(words) if words else 10.0


def _is_line_number_leaf(region: Region) -> bool:
    lines = [ln for b in region.blocks for ln in b.lines]
    if len(lines) < 3:
        return False
    return all(_LINE_NUMBER_RE.match(ln.text.strip()) for ln in lines) and region.bbox.width < 40


def analyze_layout(pages: list[Page], options: ParseOptions, doc: Document) -> None:
    body_words: list[list[Word]] = []
    for page in pages:
        upright = [w for w in page.words if w.angle == 0]
        rotated = [w for w in page.words if w.angle != 0]
        lowconf = [w for w in upright if w.confidence is not None and w.confidence < MIN_WORD_CONFIDENCE]
        if lowconf:
            low_ids = {id(w) for w in lowconf}
            upright = [w for w in upright if id(w) not in low_ids]
            page.extras.append(
                Block(
                    lines=build_lines(lowconf),
                    bbox=BBox.enclosing(w.bbox for w in lowconf),
                    page=page.number,
                    kind=BlockKind.NOISE,
                )
            )
        blocks = _rotated_blocks(page, rotated, BBox.enclosing(w.bbox for w in upright))
        page.furniture += [b for b in blocks if b.kind.is_furniture]
        page.extras[:0] = [b for b in blocks if not b.kind.is_furniture]
        page.lines = build_lines(upright)
        body_words.append(upright)

    furn = detect_furniture(pages)
    for pi, page in enumerate(pages):
        removed: set[int] = set()
        for li, ln in enumerate(page.lines):
            kind = furn.get((pi, li))
            if kind is None:
                continue
            page.furniture.append(Block(lines=[make_line(ln.words)], bbox=ln.bbox, page=page.number, kind=kind))
            removed.update(id(w) for w in ln.words)
        words = [w for w in body_words[pi] if id(w) not in removed]
        if not words:
            page.layout = Region(RegionKind.STACK, BBox(0, 0, page.width, page.height), id="r")
            continue
        seg = Segmenter(page.width, page.height, body_size=page_body_size(words), rules=page.rules)
        page.layout = seg.segment(words)
        fill_leaves(page.layout, page.number)
        # move OCR noise and line-number columns out of the body
        for region in page.layout.iter_regions():
            if region.kind is not RegionKind.LEAF:
                continue
            if _is_line_number_leaf(region):
                for b in region.blocks:
                    b.kind = BlockKind.MARGINAL
                page.extras.extend(region.blocks)
                region.blocks = []
                continue
            keep: list[Block] = []
            for b in region.blocks:
                if any(w.confidence is not None for ln in b.lines for w in ln.words) and is_ocr_noise(b):
                    b.kind = BlockKind.NOISE
                    page.extras.append(b)
                else:
                    keep.append(b)
            region.blocks = keep
        page.stats["body_size"] = round(seg.body_size or 0, 2)

    body = doc.body_size = document_body_size(pages)
    all_blocks = [b for p in pages for b in p.blocks]
    classify_headings(all_blocks, body)
    for page in pages:
        if page.layout is not None:
            detect_synopsis(page.layout, lambda r: " ".join(b.raw_text for b in r.iter_blocks()))
