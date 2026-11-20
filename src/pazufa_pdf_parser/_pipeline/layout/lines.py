"""Grouping words into lines."""

from __future__ import annotations

from statistics import median

from ..model import BBox, Line, Word


def median_size(words: list[Word], default: float = 10.0) -> float:
    sizes = [w.size if w.size > 0 else w.bbox.height for w in words]
    return median(sizes) if sizes else default


def tab_threshold(size: float) -> float:
    """Horizontal gap (pt) above which two words of a line are separated by a tab."""
    return max(2.0 * size, 16.0)


def split_cells(words: list[Word]) -> list[list[Word]]:
    """Split a line's words (left to right) into cells at gaps wider than :func:`tab_threshold`."""
    cells: list[list[Word]] = []
    for w in words:
        prev = cells[-1][-1] if cells else None
        if prev is None or w.bbox.x0 - prev.bbox.x1 > tab_threshold(max(prev.size, w.size, 1.0)):
            cells.append([w])
        else:
            cells[-1].append(w)
    return cells


def join_words(words: list[Word]) -> str:
    return "\t".join(" ".join(w.text for w in cell) for cell in split_cells(words))


def make_line(words: list[Word]) -> Line:
    words = sorted(words, key=lambda w: w.bbox.x0)
    return Line(words=words, bbox=BBox.enclosing(w.bbox for w in words), text=join_words(words))


def build_lines(words: list[Word]) -> list[Line]:
    """Cluster upright words into lines by vertical position, sorted top-down.

    Words are assigned to the line whose vertical span they overlap most (>= 50%
    of the smaller height); this tolerates sub/superscripts and slight scan skew.
    """
    if not words:
        return []
    ws = sorted(words, key=lambda w: (w.bbox.cy, w.bbox.x0))
    rows: list[list[Word]] = []
    spans: list[tuple[float, float]] = []  # running core y-span per row
    for w in ws:
        h = max(w.bbox.height, 0.1)
        best, best_ov = -1, 0.0
        # only the most recent rows can overlap since words are sorted by cy
        for i in range(len(rows) - 1, max(-1, len(rows) - 4), -1):
            y0, y1 = spans[i]
            ov = min(y1, w.bbox.y1) - max(y0, w.bbox.y0)
            if ov <= 0:
                continue
            ratio = ov / min(h, max(y1 - y0, 0.1))
            # refuse to put two words on the same row if they overlap horizontally
            if ratio >= 0.5 and ratio > best_ov and not any(_x_collide(w, o) for o in rows[i]):
                best, best_ov = i, ratio
        if best >= 0:
            rows[best].append(w)
            y0, y1 = spans[best]
            # keep the span anchored to the row's dominant words (do not grow with superscripts)
            if h >= 0.8 * (y1 - y0):
                spans[best] = (min(y0, w.bbox.y0) * 0.5 + y0 * 0.5, max(y1, w.bbox.y1) * 0.5 + y1 * 0.5)
        else:
            rows.append([w])
            spans.append((w.bbox.y0, w.bbox.y1))
    lines = [make_line(r) for r in rows]
    lines.sort(key=lambda ln: (ln.bbox.y0, ln.bbox.x0))
    return lines


def _x_collide(a: Word, b: Word) -> bool:
    ov = a.bbox.x_overlap(b.bbox)
    return ov > 0.5 * min(a.bbox.width, b.bbox.width, 1e9) and ov > 1.0
