"""Detection of page furniture: running headers, footers and page numbers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..model import BlockKind, Line, Page

BAND = 0.14  # fraction of the page height considered header / footer zone
MAX_BAND_LINES = 5  # association letters print "1 von 3" above a four-line footer
SIMILAR = 0.85  # fuzzy match ratio for repeated header/footer lines
REPEAT_SHARE = 0.4  # below one half: left/right pages carry different running headers
MIN_KEY_LEN = 3  # keys like "#" (a bare number) would repeat on every page

_PAGE_WORD = r"(?:seite|page|s\.|blatt)"
_ROMAN = r"(?=[ivxl])(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"  # up to 89 for front matter; rejects OCR "ll"
_PAGE_NUMBER_RES = [
    re.compile(r"^[-–—]?\s*\d{1,4}\s*[-–—]?$"),
    re.compile(rf"^{_PAGE_WORD}\s*\d{{1,4}}(\s*(von|of|/)\s*\d{{1,4}})?\.?$", re.I),
    re.compile(r"^\d{1,4}\s*(/|von|of)\s*\d{1,4}$", re.I),
    re.compile(rf"^{_ROMAN}$", re.I),
]
_PAGE_WORD_NUMBER = re.compile(rf"\b{_PAGE_WORD}\s*(\d{{1,4}})\b", re.I)  # "… | Seite 1 von 2" in a header
# page 1 masthead ending in the document's own number: "Landtag von Baden-Württemberg<tab>Drucksache 17 / 273"
_MASTHEAD = re.compile(r"(^|\t(\d{1,2}\.\d{1,2}\.\d{4} )?)(Drucksache|Plenarprotokoll) \d+ ?/ ?\d+$")


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
    other pages. The first line of the first page is a header also without
    repetition when it is a Drucksache or Plenarprotokoll masthead.
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
                # a colon marks an e-mail field instead ("Betreff:<tab>Drucksache 18/123")
                if pi == li == which == 0 and ":" not in ln.text and _MASTHEAD.search(ln.text):
                    result[(pi, li)] = kind
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


def assign_printed_pages(pages: list[Page]) -> None:
    """Set ``printed_page``: a page-number line, else "Seite N" in a header or footer, else a number
    opening or closing a header or footer line that the next or previous page continues (N±1)."""
    own = [_own_numbers(p) for p in pages]
    edges = [_edge_numbers(p) for p in pages]
    for i, page in enumerate(pages):
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(pages)]  # parsed pages are a contiguous range
        # a number the next page repeats is a year, a phone number or a document number
        steady = [n for n in own[i] if not any(n in own[j] for j in near)]
        counted = [str(n) for n in edges[i] if any(n + j - i in edges[j] and n not in edges[j] for j in near)]
        page.printed_page = next(iter(steady + counted), None)


def _own_numbers(page: Page) -> list[str]:
    """Page-number lines first ("- 2 -", "2 / 5", "II"), then "Seite N" inside headers and footers."""
    lines = [" ".join(b.raw_text.split()) for b in page.furniture if b.kind is BlockKind.PAGE_NUMBER]
    found = [m.group() if (m := re.search(r"\d+", t)) else t for t in lines]
    others = [b.raw_text for b in page.furniture if b.kind is not BlockKind.PAGE_NUMBER]
    return found + [m.group(1) for t in others for m in _PAGE_WORD_NUMBER.finditer(t)]


def _edge_numbers(page: Page) -> list[int]:
    """Numbers opening or closing a header or footer line, top-down: "178 Bayerisches …", "… Wahlperiode 1"."""
    tokens = [ln.text.split() for b in page.furniture for ln in b.lines]
    # isdecimal: a footnote mark "²" is a digit to isdigit() but not a number to int()
    return [int(t) for ts in tokens for t in ts[:1] + ts[-1:] if t.isdecimal() and len(t) <= 4]
