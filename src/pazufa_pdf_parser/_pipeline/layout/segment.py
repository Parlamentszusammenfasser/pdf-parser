"""Page segmentation: recursive XY-cut with gutter-compatible strip grouping.

The page body is cut horizontally into strips at whitespace rows. Consecutive
strips sharing a common vertical whitespace gutter are grouped and split into
columns (recursively); consecutive single-column strips form a leaf. This keeps
paragraph flow intact while handling letter sidebars, multi-column articles and
two-column synopses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from ..model import BBox, Line, Region, RegionKind, Word
from .lines import build_lines, median_size

MAX_DEPTH = 10
ROW_TOLERANCE = 0.3  # of a line height: centres closer than this sit on one printed row

Interval = tuple[float, float]


@dataclass
class _Strip:
    words: list[Word]
    x0: float
    x1: float
    free: list[Interval]  # x-intervals not covered by any word (inside page bounds)


@dataclass
class _Group:
    strips: list[_Strip] = field(default_factory=list)
    free: list[Interval] = field(default_factory=list)
    columns: bool = False

    @property
    def words(self) -> list[Word]:
        return [w for s in self.strips for w in s.words]

    @property
    def x0(self) -> float:
        return min(s.x0 for s in self.strips)

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.strips)


def _union(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _complement(covered: list[Interval], lo: float, hi: float) -> list[Interval]:
    free: list[Interval] = []
    cur = lo
    for a, b in covered:
        if a > cur:
            free.append((cur, a))
        cur = max(cur, b)
    if cur < hi:
        free.append((cur, hi))
    return free


def _intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


class Segmenter:
    def __init__(self, page_width: float, page_height: float, body_size: float | None = None):
        self.page_width = page_width
        self.page_height = page_height
        self.body_size = body_size

    # ------------------------------------------------------------------ helpers
    def _min_gutter(self, words: list[Word]) -> float:
        size = self.body_size or median_size(words)
        return max(1.0 * size, 7.0)

    def _hsplit(self, words: list[Word]) -> list[list[Word]]:
        size = self.body_size or median_size(words)
        min_gap = max(0.15 * size, 1.0)
        ws = sorted(words, key=lambda w: w.bbox.y0)
        strips: list[list[Word]] = []
        cur: list[Word] = []
        bottom = -1e9
        for w in ws:
            if cur and w.bbox.y0 - bottom > min_gap:
                strips.append(cur)
                cur = []
            cur.append(w)
            bottom = max(bottom, w.bbox.y1) if len(cur) > 1 else w.bbox.y1
        if cur:
            strips.append(cur)
        return strips

    def _strip(self, words: list[Word]) -> _Strip:
        cov = _union([(w.bbox.x0, w.bbox.x1) for w in words])
        return _Strip(words, cov[0][0], cov[-1][1], _complement(cov, 0.0, self.page_width))

    def _interior(self, free: list[Interval], x0: float, x1: float, min_w: float) -> list[Interval]:
        return [(a, b) for a, b in free if a > x0 and b < x1 and b - a >= min_w]

    def _group(self, strips: list[_Strip], min_w: float) -> list[_Group]:
        groups: list[_Group] = []
        for s in strips:
            own = self._interior(s.free, s.x0, s.x1, min_w)
            g = groups[-1] if groups else None
            if g is not None and g.columns:
                free = _intersect(g.free, s.free)
                gutters = self._interior(free, min(g.x0, s.x0), max(g.x1, s.x1), min_w)
                if gutters and not self._new_columns(s, own, gutters):
                    g.strips.append(s)
                    g.free = free
                    continue
            elif g is not None and not own:
                g.strips.append(s)
                continue
            groups.append(_Group([s], s.free, bool(own)))
        return groups

    def _new_columns(self, s: _Strip, own: list[Interval], gutters: list[Interval]) -> bool:
        """The strip holds columns of its own that the group's gutters miss. BW page 1 prints its
        number "1" right of the body, so the margin gap left of it would take in the two-column footer."""
        if not own or _intersect(gutters, own):
            return False
        return self._accept_columns(s.words, max(own, key=lambda iv: iv[1] - iv[0]))

    def _accept_columns(self, words: list[Word], gap: Interval) -> bool:
        lines = build_lines(words)
        if len(lines) < 2:
            return False  # a single tabbed row is kept as one line
        left_words = [w for w in words if w.bbox.cx < gap[0]]
        right_words = [w for w in words if w.bbox.cx >= gap[1]]
        if not left_words or not right_words:
            return False
        lx0 = min(w.bbox.x0 for w in left_words)
        rx1 = max(w.bbox.x1 for w in right_words)
        total = max(rx1 - lx0, 1.0)
        lw = gap[0] - lx0
        rw = rx1 - gap[1]
        # list markers, labels, line numbers next to text: rows of a table, not columns
        if min(lw, rw) < max(0.15 * total, 45.0):
            return False
        left_lines = build_lines(left_words)
        colon = sum(1 for ln in left_lines if ln.text.rstrip().endswith(":"))
        # label column ("Von:", "Berichterstatter:") -> key/value table, keep rows
        if colon / len(left_lines) >= 0.5 and len(left_lines) <= 12:
            return False
        return True

    # ------------------------------------------------------------------ main
    def segment(self, words: list[Word]) -> Region:
        region = self._segment(words, 0)
        _assign_ids(region, "r")
        return region

    def _leaf(self, words: list[Word]) -> Region:
        bbox = BBox.enclosing(w.bbox for w in words)
        return Region(RegionKind.LEAF, bbox, words=words)

    def _segment(self, words: list[Word], depth: int) -> Region:
        if not words:
            return Region(RegionKind.STACK, BBox(0, 0, 0, 0))
        if depth >= MAX_DEPTH or len(words) == 1:
            return self._leaf(words)
        min_w = self._min_gutter(words)
        strips = [self._strip(s) for s in self._hsplit(words)]
        groups = self._group(strips, min_w)
        # decide column splits, then merge rejected groups into neighbouring flow groups
        decided: list[tuple[list[Word], Interval | None]] = []
        for g in groups:
            gap = None
            if g.columns:
                gaps = self._interior(g.free, g.x0, g.x1, min_w)
                if gaps:
                    cand = max(gaps, key=lambda iv: iv[1] - iv[0])
                    if self._accept_columns(g.words, cand):
                        gap = cand
            if gap is None and decided and decided[-1][1] is None:
                decided[-1][0].extend(g.words)
            else:
                decided.append((list(g.words), gap))
        decided = _absorb_one_sided(decided)
        children: list[Region] = []
        for gw, gap in decided:
            region = None
            if gap is not None:
                mid = (gap[0] + gap[1]) / 2
                left = [w for w in gw if w.bbox.cx < mid]
                right = [w for w in gw if w.bbox.cx >= mid]
                if left and right:
                    region = Region(
                        RegionKind.COLUMNS,
                        BBox.enclosing(w.bbox for w in gw),
                        children=[self._segment(left, depth + 1), self._segment(right, depth + 1)],
                    )
                    region.aside_first = _is_sidebar(left, right)
            if region is None:
                region = self._leaf(gw)
            children.append(region)
        if len(children) == 1:
            return children[0]
        return Region(RegionKind.STACK, BBox.enclosing(c.bbox for c in children), children=_flatten(children))


def _is_sidebar(left: list[Word], right: list[Word]) -> bool:
    """A narrow right column next to a wide one is a sidebar (letterhead data), unless the two pair
    up line for line in one font size like the two signature lists under a Gesetzblatt law. A letter's
    sidebar may align with the address field, but in smaller print."""
    lw = max(w.bbox.x1 for w in left) - min(w.bbox.x0 for w in left)
    rw = max(w.bbox.x1 for w in right) - min(w.bbox.x0 for w in right)
    if rw >= 0.45 * (lw + rw) or lw < 1.2 * rw:
        return False
    lines, aside = build_lines(left), build_lines(right)
    paired = len(lines) == len(aside) > 1
    return not (paired and all(_same_row(a, b) for a, b in zip(lines, aside)))


def _same_row(a: Line, b: Line) -> bool:
    return abs(a.bbox.cy - b.bbox.cy) < ROW_TOLERANCE * a.bbox.height and abs(a.size - b.size) < 0.15 * a.size


def _fits(words: list[Word], gap: Interval) -> bool:
    return all(w.bbox.x1 <= gap[0] + 0.5 for w in words) or all(w.bbox.x0 >= gap[1] - 0.5 for w in words)


def _absorb_one_sided(decided: list[tuple[list[Word], Interval | None]]) -> list[tuple[list[Word], Interval | None]]:
    """Merge flow groups lying entirely on one side of an adjacent column gutter into it
    (e.g. a column that continues alone at the top of the next page)."""
    out = list(decided)
    i = 0
    while i < len(out):
        words, gap = out[i]
        if gap is None:
            nxt = out[i + 1] if i + 1 < len(out) else None
            prv = out[i - 1] if i > 0 else None
            if nxt is not None and nxt[1] is not None and _fits(words, nxt[1]):
                out[i + 1] = (words + nxt[0], nxt[1])
                del out[i]
                continue
            if prv is not None and prv[1] is not None and _fits(words, prv[1]):
                out[i - 1] = (prv[0] + words, prv[1])
                del out[i]
                continue
        i += 1
    return out


def _flatten(children: list[Region]) -> list[Region]:
    out: list[Region] = []
    for c in children:
        if c.kind is RegionKind.STACK:
            out.extend(c.children)
        else:
            out.append(c)
    return out


def _assign_ids(region: Region, prefix: str) -> None:
    region.id = prefix
    for i, c in enumerate(region.children):
        _assign_ids(c, f"{prefix}.{i}")


def detect_synopsis(region: Region, text_of) -> None:
    """Mark two-column regions whose columns are parallel versions of one text."""
    for r in region.iter_regions():
        if r.kind is not RegionKind.COLUMNS or len(r.children) != 2:
            continue
        left, right = r.children
        if min(left.bbox.width, right.bbox.width) < 0.3 * r.bbox.width:
            continue
        lt, rt = text_of(left), text_of(right)
        if len(lt) < 80 or len(rt) < 20:
            continue
        lw = {t for t in lt.lower().split() if len(t) > 3}
        rw = {t for t in rt.lower().split() if len(t) > 3}
        if not lw or not rw:
            continue
        overlap = len(lw & rw) / min(len(lw), len(rw))
        markers = (
            "unverändert",
            "ausschussvorschlag",
            "geltende fassung",
            "neue fassung",
            "synopse",
            "beschlüsse des",
            "entwurf",
            "gesetzentwurf",
        )
        has_marker = any(m in (lt + rt).lower() for m in markers)
        if overlap >= 0.45 or (has_marker and overlap >= 0.2):
            r.synopsis = True


def page_body_size(words: list[Word]) -> float:
    """Character-weighted median font size."""
    sizes: list[float] = []
    for w in words:
        sizes.extend([w.size or w.bbox.height] * max(1, len(w.text)))
    return median(sizes) if sizes else 10.0
