"""Detection of page furniture: running headers, footers and page numbers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..model import BBox, Block, BlockKind, Line, Page
from .lines import make_line, split_cells

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
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
_PAGE_WORD_NUMBER = re.compile(rf"\b{_PAGE_WORD}\s*(\d{{1,4}})\b", re.I)  # "… | Seite 1 von 2" in a header
# page 1 masthead ending in the document's own number: "Landtag von Baden-Württemberg<tab>Drucksache 17 / 273"
_MASTHEAD = re.compile(r"(^|\t(\d{1,2}\.\d{1,2}\.\d{4} )?)(Drucksache|Plenarprotokoll) \d+ ?/ ?\d+$")
# a two-page Gesetzblatt issue prints its running header once, on page 2
_GAZETTE_HEADER = re.compile(r"^Gesetzblatt für .+, Jahrgang \d{4}, Nr\. \d+ vom \d{1,2}\. \w+ \d{4}$")


def is_page_number(text: str) -> bool:
    t = " ".join(text.split())
    return any(r.match(t) for r in _PAGE_NUMBER_RES)


def page_number_value(text: str) -> int | None:
    """The number a page-number text counts: "- 2 -", "2 / 5" and "Seite 2" give 2, "II" gives 2."""
    if not is_page_number(text):
        return None
    if m := re.search(r"\d+", text):
        return int(m.group())
    values = [_ROMAN_VALUES[c] for c in text.strip().lower()]
    return sum(-v if v < nxt else v for v, nxt in zip(values, [*values[1:], 0], strict=True))


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
    repetition when it is a Drucksache or Plenarprotokoll masthead, the first
    line of any page when it is a Gesetzblatt running header.
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
                if li == which == 0 and _is_one_off_header(pi, ln.text):
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


def _is_one_off_header(page_index: int, text: str) -> bool:
    if _GAZETTE_HEADER.match(text):
        return True
    # a colon marks an e-mail field instead ("Betreff:<tab>Drucksache 18/123")
    return page_index == 0 and ":" not in text and bool(_MASTHEAD.search(text))


def assign_printed_pages(pages: list[Page]) -> None:
    """Set ``printed_page``: a page-number line, else "Seite N" in a header or footer, else a number
    opening or closing a header or footer line that the next or previous page continues (N±1).

    A page number closing a band line beside other text ("Bayerisches<tab>177") becomes a page-number
    block of its own when the next or previous page continues it."""
    _split_number_cells(pages)
    own = [_own_numbers(p) for p in pages]
    edges = [_edge_numbers(p) for p in pages]
    for i, page in enumerate(pages):
        # a number the next page repeats is a year, a phone number or a document number
        steady = [n for n in own[i] if not any(n in own[j] for j in _near(i, pages))]
        counted = [
            str(n) for n in edges[i] if any(n + j - i in edges[j] and n not in edges[j] for j in _near(i, pages))
        ]
        page.printed_page = next(iter(steady + counted), None)


def _near(i: int, pages: list[Page]) -> list[int]:
    return [j for j in (i - 1, i + 1) if 0 <= j < len(pages)]  # parsed pages are a contiguous range


def _split_number_cells(pages: list[Page]) -> None:
    own = [{v for t in _own_numbers(p) if (v := page_number_value(t)) is not None} for p in pages]
    edges = [set(_edge_numbers(p)) for p in pages]
    # a year or document number the neighbour repeats counts no page; "1 / 2" and "2 / 2" share only their total
    known = [_unrepeated(own, i, pages) | _unrepeated(edges, i, pages) for i in range(len(pages))]
    for i, page in enumerate(pages):
        found = [
            (block, k, cells)
            for block in [*page.furniture, *page.blocks]
            for k, ln in enumerate(block.lines)
            if _in_band(ln, page)
            and len(cells := split_cells(ln.words)) > 1
            and (n := page_number_value(" ".join(w.text for w in cells[-1]))) is not None
            and any(n + j - i in known[j] for j in _near(i, pages))
        ]
        for block, k, cells in found:
            number = make_line(cells[-1])
            block.lines[k] = make_line([w for cell in cells[:-1] for w in cell])
            block.bbox = BBox.enclosing(ln.bbox for ln in block.lines)
            page.furniture.append(Block(lines=[number], bbox=number.bbox, page=page.number, kind=BlockKind.PAGE_NUMBER))


def _unrepeated(numbers: list[set[int]], i: int, pages: list[Page]) -> set[int]:
    return {n for n in numbers[i] if not any(n in numbers[j] for j in _near(i, pages))}


def _in_band(line: Line, page: Page) -> bool:
    return line.bbox.y0 <= page.height * BAND or line.bbox.y1 >= page.height * (1 - BAND)


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
