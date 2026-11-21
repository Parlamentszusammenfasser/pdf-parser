import pytest

from pazufa_pdf_parser._pipeline.extract.pdf import _Char, _suspect, _unmapped
from pazufa_pdf_parser._pipeline.layout.lines import make_line
from pazufa_pdf_parser._pipeline.model import (
    BBox,
    Block,
    BlockKind,
    Page,
    PageSource,
    Region,
    RegionKind,
    Word,
)
from pazufa_pdf_parser._pipeline.sanitize import (
    clean_chars,
    collapse_letterspacing,
    drop_garbled,
    fix_ocr_text,
    is_junk_line,
    is_line_structured,
    join_hyphenated,
    normalize_spaces,
    reflow_lines,
    sanitize_text,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ﬁnden und ﬂießen", "finden und fließen"),
        ("Ge­setz", "Gesetz"),  # soft hyphen inside word
        ("a​b﻿c", "abc"),  # zero-width chars
        ("A B C", "A B C"),  # exotic spaces
        (" Punkt", "• Punkt"),  # Symbol-font bullet from private use area
        ("Text(cid:12)mehr", "Textmehr"),
        ("Ctrl\x07char", "Ctrlchar"),
        ("Über", "Über"),  # NFC composition
    ],
)
def test_clean_chars(raw, expected):
    assert clean_chars(raw) == expected


def test_clean_chars_keeps_newlines():
    assert clean_chars("a\r\nb\rc") == "a\nb\nc"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A b l e h n u n g empfohlen", "Ablehnung empfohlen"),
        ("Z u s t i m m u n g", "Zustimmung"),
        ("u. a. und z. B.", "u. a. und z. B."),  # abbreviations are untouched
        ("a b c", "a b c"),  # too short to be letter-spacing
        ("Art 1 a b", "Art 1 a b"),
    ],
)
def test_collapse_letterspacing(raw, expected):
    assert collapse_letterspacing(raw) == expected


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("Parlaments-", "fragen und Integration", "Parlamentsfragen und Integration"),
        ("die CDU-", "Fraktion", "die CDU-Fraktion"),
        ("Aus-", "und Fortbildung", "Aus- und Fortbildung"),
        ("Kinderbildungs-", "oder Betreuungsgesetz", "Kinderbildungs- oder Betreuungsgesetz"),
        ("kein Trennstrich", "weiter", None),
        ("Zahl 3-", "4", None),  # hyphen after a digit is not a word division
    ],
)
def test_join_hyphenated(first, second, expected):
    assert join_hyphenated(first, second) == expected


def test_reflow_joins_wrapped_prose_and_dehyphenates():
    lines = [
        "Der Gesetzentwurf wurde dem Ausschuss für Umwelt und Verbraucherschutz",
        "federführend zugewiesen. Der Ausschuss für Verfassung, Recht, Parlaments-",
        "fragen und Integration hat den Gesetzentwurf endberaten.",
    ]
    out = reflow_lines(lines, [400, 400, 300], 400)
    assert "\n" not in out
    assert "Parlamentsfragen" in out


def test_reflow_keeps_address_lines():
    lines = ["Bayerische Staatskanzlei", "Frau Staatsrätin Muster", "Franz-Josef-Strauß-Ring 1", "80539 München"]
    assert is_line_structured(lines)
    assert reflow_lines(lines) == "\n".join(lines)


def test_reflow_keeps_label_lines():
    lines = ["CSU: Ablehnung", "FREIE WÄHLER: Ablehnung", "SPD: Zustimmung"]
    out = reflow_lines(lines, [100, 140, 100], 140)
    assert out.split("\n") == lines


def test_reflow_keeps_mail_header_lines():
    lines = [
        "Von: Thomas Schmid <t@example.org>",
        "An: Referat B6 <r@example.org>",
        "Betreff: Verbandsanhörung zum Gesetzentwurf der Staatsregierung",
    ]
    assert reflow_lines(lines, [300, 280, 420], 420).count("\n") == 2


def test_normalize_spaces():
    assert normalize_spaces("a\t\tb   c ,d ( e )") == "a b c,d (e)"


@pytest.mark.parametrize(
    "line,junk", [("___________", True), ("- . ' ,", True), ("§", False), ("Text", False), ("", True)]
)
def test_is_junk_line(line, junk):
    assert is_junk_line(line) is junk


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Zu 8 3 drittes Modernisierungsgesetz", "Zu § 3 drittes Modernisierungsgesetz"),
        ("Zu 87 Nr. 1 —- Änderungen", "Zu § 7 Nr. 1 – Änderungen"),
        ("gemäß 8 5 Abs. 2 BayBO", "gemäß § 5 Abs. 2 BayBO"),
        ("Gebäude bis 20 m? Brutto-Rauminhalt", "Gebäude bis 20 m² Brutto-Rauminhalt"),
        ("Wilfried’Mück", "Wilfried Mück"),
        ("zu 80 Prozent", "zu 80 Prozent"),  # genuine numbers stay
        ("am 8. Mai", "am 8. Mai"),
    ],
)
def test_fix_ocr_text(raw, expected):
    assert fix_ocr_text(raw) == expected


def test_sanitize_text_end_to_end():
    raw = "Erste Zeile mit Tren-\nnung und ﬁ-Ligatur.\n\n____________\n\nZweiter   Absatz."
    assert sanitize_text(raw) == "Erste Zeile mit Trennung und fi-Ligatur.\n\nZweiter Absatz."


def _garbled_page(source=PageSource.TEXT, garbage_ratio=0.9, more=()):
    """A BW annex page: a clean header font above body text in a font shifted by ASCII +29, then
    one block per word list in ``more``."""
    header = [Word("Drucksache", BBox(70, 40, 130, 52), font="TimesNewRomanPSMT")]
    body = [
        Word("\x03\x14\x17", BBox(70, 200, 90, 212), font="NDJBHD+ArialMT", garbage=3),
        Word("(LQJDQJ", BBox(95, 200, 140, 212), font="NDJBHD+ArialMT"),
    ]
    lines = [header, body, *more]
    blocks = [Block(lines=[make_line(ws)], bbox=BBox.enclosing(w.bbox for w in ws), page=1) for ws in lines]
    page = Page(number=1, width=595, height=842, source=source, words=[w for ws in lines for w in ws])
    page.garbage_ratio = garbage_ratio
    page.layout = Region(RegionKind.LEAF, BBox(0, 0, 595, 842), blocks=blocks)
    return page


ARIAL = "NDJBHD+ArialMT"
GARBLED = "\x03\x14\x17 (LQJDQJ"


def _word(text, font="TimesNewRomanPSMT", garbage=0):
    return Word(text, BBox(70, 300, 70 + 6 * len(text), 312), font=font, garbage=garbage)


@pytest.mark.parametrize(
    "page,dropped",
    [
        (_garbled_page(), [GARBLED]),
        (_garbled_page(more=[[_word("Landtag"), _word("Baden-Württemberg"), _word("\x03", ARIAL, 1)]]), [GARBLED]),
        (_garbled_page(more=[[_word("Stuttgart", "")], [_word("\x01\x02", "", 2)]]), [GARBLED, "\x01\x02"]),
        (_garbled_page(source=PageSource.OCR), []),
        (_garbled_page(garbage_ratio=0.05), []),
        (Page(number=1, width=595, height=842), []),
    ],
    ids=["garbled-font", "mostly-clean-block", "nameless-font", "ocr-replaced-it", "clean-text-layer", "empty-page"],
)
def test_drop_garbled(page, dropped):
    # the shifted font's letter words ("(LQJDQJ") go with its control characters; the clean header stays
    assert drop_garbled(page, 0.15) == len(dropped)
    assert [b.raw_text for b in page.extras] == dropped
    assert all(b.kind is BlockKind.NOISE for b in page.extras)
    assert not {b.raw_text for b in page.blocks} & set(dropped)


@pytest.mark.parametrize(
    "ch,suspect,unmapped",
    [("\x00A", True, True), ("\x03", True, True), ("�", True, True), ("", True, False), ("a", False, False)],
    ids=["map-error", "control", "replacement", "private-use-symbol", "letter"],
)
def test_garbage_chars(ch, suspect, unmapped):
    # a symbol font's bullets and digits sit in the private use area: the page may need OCR, but the
    # font is not broken, so its text must not be dropped as garbled
    c = _Char(ch, BBox(0, 0, 1, 1), 10, "Symbol", False, False, 0, False, False)
    assert (_suspect(c), _unmapped(c)) == (suspect, unmapped)
