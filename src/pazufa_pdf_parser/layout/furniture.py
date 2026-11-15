"""Detection of page furniture: running headers, footers and page numbers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..model import BlockKind, Line, Page

BAND = 0.14  # fraction of the page height considered header / footer zone
MAX_BAND_LINES = 4
SIMILAR = 0.85  # fuzzy match ratio for repeated header/footer lines
REPEAT_SHARE = 0.4  # below one half: left/right pages carry different running headers
MIN_KEY_LEN = 3  # keys like "#" (a bare number) would repeat on every page

_PAGE_NUMBER_RES = [
    re.compile(r"^[-–—]?\s*\d{1,4}\s*[-–—]?$"),
    re.compile(r"^(seite|page|s\.|blatt)\s*\d{1,4}(\s*(von|of|/)\s*\d{1,4})?\.?$", re.I),
    re.compile(r"^\d{1,4}\s*(/|von|of)\s*\d{1,4}$", re.I),
    re.compile(r"^[ivxlc]{1,6}$", re.I),
]


def is_page_number(text: str) -> bool:
    t = " ".join(text.split())
    return any(r.match(t) for r in _PAGE_NUMBER_RES)


def normalize_key(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\d+", "#", t)
    t = re.sub(r"[^\w#]+", " ", t)
    return " ".join(t.split())


def _band_lines(page: Page) -> tuple[list[Line], list[Line]]:
    top = [ln for ln in page.lines if ln.bbox.y0 <= page.height * BAND][:MAX_BAND_LINES]
    bottom = [ln for ln in page.lines if ln.bbox.y1 >= page.height * (1 - BAND)][-MAX_BAND_LINES:]
    return top, bottom


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # order-insensitive comparison handles alternating (even/odd) header layouts
    ta, tb = sorted(a.split()), sorted(b.split())
    if ta == tb:
        return True
    return _close(a, b) or _close(" ".join(ta), " ".join(tb))


def _close(a: str, b: str) -> bool:
    # the cheap upper bounds reject most pairs; full ratio() made a 49-page protocol take ~10 s
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= SIMILAR and m.quick_ratio() >= SIMILAR and m.ratio() >= SIMILAR


def detect_furniture(pages: list[Page]) -> dict[tuple[int, int], BlockKind]:
    """Return ``{(page_index, line_index): kind}`` for furniture lines.

    A line in the top/bottom band is furniture if it is a page number or if a
    similar line (digits normalised, fuzzy) appears in the same band on enough
    other pages.
    """
    result: dict[tuple[int, int], BlockKind] = {}
    bands: list[tuple[list[Line], list[Line]]] = [_band_lines(p) for p in pages]
    keys = [([normalize_key(ln.text) for ln in top], [normalize_key(ln.text) for ln in bot]) for top, bot in bands]
    n = len(pages)
    need = max(1, round(REPEAT_SHARE * (n - 1))) if n > 1 else None
    for pi, page in enumerate(pages):
        index = {id(ln): li for li, ln in enumerate(page.lines)}
        for which, kind in ((0, BlockKind.HEADER), (1, BlockKind.FOOTER)):
            lines = bands[pi][which]
            for k, ln in enumerate(lines):
                li = index[id(ln)]
                if is_page_number(ln.text):
                    result[(pi, li)] = BlockKind.PAGE_NUMBER
                    continue
                key = keys[pi][which][k]
                if need is None or len(key) < MIN_KEY_LEN:
                    continue
                hits = 0
                for pj in range(n):
                    if pj != pi and any(_similar(key, other) for other in keys[pj][which]):
                        hits += 1
                        if hits >= need:
                            result[(pi, li)] = kind
                            break
    # trailing/leading page numbers glued to a header line ("... Wahlperiode   12") are
    # handled by the similarity test because digits are normalised.
    return result
