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
# the document's own number closing the first line: "Landtag von Baden-Württemberg<tab>Drucksache 17 / 273",
# "Plenarprotokoll 18 / 10"; prose would run on without a tab gap
_MASTHEAD = re.compile(r"(^|\t[^\t]*\b)(Drucksache|Plenarprotokoll) \d+ ?/ ?\d+$")
_ROMAN = re.compile(r"^(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)  # up to 89: front matter; rejects OCR "ll"
_SEITE = re.compile(r"\b(?:seite|page|blatt) (\d{1,4})\b", re.I)


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
                # masthead, also with no page to repeat it; a colon marks an e-mail "Betreff:" field instead
                if li == 0 and which == 0 and ":" not in ln.text and _MASTHEAD.search(ln.text):
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
    leading or closing a header or footer line that the next or previous page continues (N±1)."""
    edges = [_edge_numbers(p) for p in pages]
    for i, page in enumerate(pages):
        page.printed_page = _own_number(page)
        if page.printed_page is not None:
            continue
        for n in edges[i]:
            before = i > 0 and pages[i - 1].number == page.number - 1 and n - 1 in edges[i - 1]
            after = i + 1 < len(pages) and pages[i + 1].number == page.number + 1 and n + 1 in edges[i + 1]
            if before or after:
                page.printed_page = str(n)
                break


def _own_number(page: Page) -> str | None:
    blocks = sorted(page.furniture, key=lambda b: b.kind is not BlockKind.PAGE_NUMBER)
    for b in blocks:
        text = " ".join(b.raw_text.split())
        if b.kind is BlockKind.PAGE_NUMBER:
            # "- 2 -", "2 / 5", "Seite 2 von 5" print page 2
            if m := re.search(r"\d+", text):
                return m.group()
            if _ROMAN.match(text):
                return text
        elif m := _SEITE.search(text):
            return m.group(1)
    return None


def _edge_numbers(page: Page) -> set[int]:
    """Numbers opening or closing a header or footer line: "178 Bayerisches Gesetz- …", "… Wahlperiode 1"."""
    found: set[int] = set()
    for b in page.furniture:
        for ln in b.lines:
            tokens = ln.text.split()
            found.update(int(t) for t in tokens[:1] + tokens[-1:] if t.isdigit() and len(t) <= 4)
    return found
