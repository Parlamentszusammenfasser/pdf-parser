"""Layout analysis: lines, furniture, segmentation, blocks, headings."""

from __future__ import annotations

import copy
import re

from ..._options import ParseOptions
from ..model import BBox, Block, BlockKind, Document, Page, Region, RegionKind, Word, rotate_words
from ..sanitize import is_ocr_noise
from .blocks import classify_headings, fill_leaves
from .furniture import detect_furniture
from .lines import build_lines, make_line
from .segment import Segmenter, detect_synopsis, page_body_size

__all__ = ["analyze_layout", "document_body_size", "MIN_WORD_CONFIDENCE"]

MIN_WORD_CONFIDENCE = 25.0  # OCR words below this tesseract confidence are mostly specks and stamps

_LINE_NUMBER_RE = re.compile(r"^\d{1,4}$")


def _marginal_blocks(page: Page, words: list[Word]) -> list[Block]:
    """Rotated text: group per direction, rebuild lines in an upright frame."""
    out: list[Block] = []
    by_angle: dict[int, list[Word]] = {}
    for w in words:
        by_angle.setdefault(w.angle, []).append(w)
    for angle, ws in by_angle.items():
        copies = [copy.copy(w) for w in ws]
        rotate_words(copies, page.width, page.height, (360 - angle) % 360)
        lines = build_lines(copies)
        if lines:
            out.append(
                Block(lines=lines, bbox=BBox.enclosing(w.bbox for w in ws), page=page.number, kind=BlockKind.MARGINAL)
            )
    return out


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
        page.extras[:0] = _marginal_blocks(page, rotated)
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
        seg = Segmenter(page.width, page.height, body_size=page_body_size(words))
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
