"""Second-pass footer detection (layout.footers) and the furniture/flow steps."""

from dataclasses import replace

import pytest

from conftest import NO_OCR
from pazufa_pdf_parser import BlockKind, parse, render
from pazufa_pdf_parser._pipeline.extract.pdf import plausible_size
from pazufa_pdf_parser._pipeline.layout.footers import footer_score, lexicon_hits, zone_page_number
from pazufa_pdf_parser._pipeline.model import BBox
from pazufa_pdf_parser._pipeline.pipeline import Pipeline
from pdfgen import T, make_pdf, paragraph

PROSE = [
    "Der Ausschuss hat den Gesetzentwurf in seiner Sitzung beraten und",
    "mit großer Mehrheit die Annahme in der vorliegenden Fassung empfohlen.",
    "Die Beratungen werden in der kommenden Woche im Plenum fortgesetzt.",
]


def body(y=100):
    return paragraph(70, y, PROSE, 11)


def footer_lines(doc):
    """(page, first line) of every footer block."""
    return [(b.page, b.text.split("\n")[0]) for b in doc.blocks if b.kind is BlockKind.FOOTER]


def test_single_page_small_footer_note_removed():
    pdf = make_pdf([body() + [T(70, 790, "Drucksachen sind im Internet unter www.landtag.example abrufbar.", 8)]])
    d = parse(pdf, NO_OCR)
    assert footer_lines(d) == [(1, "Drucksachen sind im Internet unter www.landtag.example abrufbar.")]
    assert "abrufbar" not in render(d, "txt")
    assert "abrufbar" in render(d, "raw")


def test_first_page_only_letter_footer_removed():
    p1 = body() + [
        T(70, 780, "Geschäftsführer: Dr. Max Muster · Registergericht München VR 12345", 7),
        T(70, 790, "Bankverbindung: Sparkasse · IBAN DE89 3704 0044 0532 0130 00", 7),
    ]
    p2 = body() + [T(70, 300, "Mit freundlichen Grüßen", 11)]
    d = parse(make_pdf([p1, p2]), NO_OCR)
    assert {n for n, _ in footer_lines(d)} == {1}
    txt = render(d, "txt")
    assert "Registergericht" not in txt and "IBAN" not in txt
    assert "Mit freundlichen Grüßen" in txt


def test_varying_logo_text_is_detected_by_tolerant_repetition():
    logos = ["DAS HANDWERK", "DAS HANZWERK", "DAS"]  # OCR reads the logo differently on every page
    pages = [body() + [T(400, 780, logo, 16, True)] for logo in logos]
    d = parse(make_pdf(pages), NO_OCR)
    # pages 1/2 are similar enough for the repetition pass in `layout`; page 3 ("DAS")
    # is only caught by the token-tolerant second pass
    assert all(any(b.kind is BlockKind.FOOTER for b in p.blocks) for p in d.pages)
    assert (3, "DAS") in footer_lines(d)
    assert "DAS" not in render(d, "txt")


def test_text_running_to_page_bottom_is_kept():
    lines = [
        f"Zeile {i} eines langen Redebeitrags, der bis an den Seitenrand reicht und weitergeht." for i in range(50)
    ]
    d = parse(make_pdf([paragraph(70, 60, lines, 11, 1.3)]), NO_OCR)
    assert footer_lines(d) == []
    assert "Zeile 49" in render(d, "txt")


def test_normal_body_paragraph_after_gap_is_kept():
    pdf = make_pdf(
        [
            body()
            + paragraph(70, 760, ["Wir bitten um Kenntnisnahme und stehen für Rückfragen gerne zur Verfügung."], 11)
        ]
    )
    d = parse(pdf, NO_OCR)
    assert footer_lines(d) == []
    assert "Kenntnisnahme" in render(d, "txt")


def test_footnotes_are_kept_and_do_not_break_the_flow():
    p1 = body() + paragraph(70, 400, ["Die Quote liegt bundesweit am niedrigsten.1 Hinzu kommt, dass die Träger"], 11)
    p1 += [T(70, 780, "1 Bertelsmann Stiftung (Hrsg.) (2026): Die Personalausstattungsquote in Kitas.", 8)]
    p2 = paragraph(70, 60, ["nur bei voller Belegung ausreichend finanziert werden."], 11)
    d = parse(make_pdf([p1, p2]), NO_OCR)
    notes = [b for b in d.blocks if b.kind is BlockKind.FOOTNOTE]
    assert len(notes) == 1 and notes[0].text.startswith("1 Bertelsmann")
    txt = render(d, "txt")
    assert "dass die Träger nur bei voller Belegung" in txt  # joined across the page break
    # each page keeps its own text; the footnote printed between the two halves follows the paragraph
    assert d.text(pages=[2]) == "nur bei voller Belegung ausreichend finanziert werden."
    assert d.text(pages=[1]).endswith(
        "dass die Träger\n\n1 Bertelsmann Stiftung (Hrsg.) (2026): Die Personalausstattungsquote in Kitas."
    )
    assert txt.index("ausreichend finanziert werden.") < txt.index("1 Bertelsmann Stiftung")


@pytest.mark.parametrize(
    "end,start,page1,page2,joined",
    [
        ("bittet die Träger", "nur bei voller Belegung", "die Träger", "nur bei", "die Träger nur bei"),
        ("Entwurfs zur Ände-", "rung des Gesetzes über", "zur Änderung", "des Gesetzes", "zur Änderung des Gesetzes"),
        (
            "die Mittel für die Aus-",
            "und Fortbildung der",
            "für die Aus-",
            "und Fortbildung",
            "die Aus- und Fortbildung",
        ),
    ],
    ids=["continued", "word-divided-at-the-break", "hyphen-kept"],
)
@pytest.mark.parametrize("blank", [0, 1], ids=["next-page", "past-a-blank-page"])
def test_paragraph_across_a_page_break_stays_on_its_pages(end, start, page1, page2, joined, blank):
    # page citations need each half on its page; a word divided at the break goes to the page it starts on
    p1 = body() + paragraph(70, 400, [f"Der Ausschuss empfiehlt nach eingehender Beratung {end}"], 11)
    p2 = paragraph(70, 60, [f"{start} die Finanzierung der Kindertagesstätten im Land."], 11)
    d = parse(make_pdf([p1, *[[]] * blank, p2]), NO_OCR)
    first = [b for b in d.pages[0].blocks if b.kind.is_body][-1]
    assert first.continues_on == 2 + blank and first.text.endswith(page1)
    assert d.pages[-1].text().startswith(page2)
    assert joined in d.text() and d.text(pages=[1]).endswith(page1)


def _bw_first_page(row_end):
    """BW Drucksache page 1: masthead date, body, dates row closed by the page number, two-column footer."""
    footer = [
        T(70, 776, "Drucksachen sind im Internet", 10),
        T(70, 785, "abrufbar: www.landtag.example", 10),
        T(300, 776, "Der Landtag druckt auf Recycling-", 10),
        T(300, 785, "papier mit dem Blauen Engel.", 10),
    ]
    masthead = [T(70, 75, "17. Wahlperiode", 14), T(400, 75, "22.6.2021", 14)]
    return masthead + body(200) + [T(70, 760, "Eingegangen: 22.6.2021 / Ausgegeben: 25.6.2021", 10), row_end] + footer


def test_first_page_footer_with_page_number_removed():
    # the footer text is barely smaller than the body; the page number closing its first row marks it
    d = parse(make_pdf([_bw_first_page(T(515, 757, "1", 14)), body(200) + [T(70, 757, "2", 14)]]), NO_OCR)
    furniture = d.pages[0].furniture_text()
    assert "Ausgegeben: 25.6.2021" in furniture and "Recyclingpapier mit dem Blauen Engel." in furniture
    assert "Ausgegeben" not in d.text() and "Recycling" not in d.text()
    assert [p.printed_page for p in d.pages] == ["1", "2"]


def test_numbered_zone_without_footer_text_is_kept():
    pdf = make_pdf([body() + [T(70, 760, "Die Kosten betragen insgesamt", 11), T(515, 760, "1", 11)]])
    d = parse(pdf, NO_OCR)
    assert footer_lines(d) == []
    assert "Die Kosten betragen insgesamt" in d.text()


def test_small_table_ending_in_numbers_is_kept():
    # statistics tables close the answers to Kleine Anfragen; a count is not the page number
    rows = [("Biberach", "12"), ("Bodenseekreis", "1"), ("Insgesamt", "13")]
    table = [t for i, (a, n) in enumerate(rows) for t in (T(70, 756 + 11 * i, a, 9), T(330, 756 + 11 * i, n, 9))]
    d = parse(make_pdf([body(690) + table]), NO_OCR)  # small print, but too close to the body for a footer
    assert footer_lines(d) == []
    assert "Bodenseekreis" in d.text()


def test_scaled_text_matrix_font_size():
    items = [T(70, 100 + i * 15, f"Zeile {i} mit skalierter Textmatrix", 11, tf_one=True) for i in range(3)]
    d = Pipeline().run(make_pdf([items]), NO_OCR)
    sizes = {round(w.size) for w in d.pages[0].words}
    assert sizes == {11}


def test_plausible_size():
    box = BBox(0, 0, 50, 11.5)
    assert plausible_size(1.0, box, 0) == 10.0
    assert plausible_size(10.5, box, 0) == 10.5
    assert plausible_size(48.0, box, 0) == 10.0


def test_scoring_helpers():
    from pazufa_pdf_parser._pipeline.model import Block, Line, Word

    def blk(text, size):
        w = Word(text, BBox(70, 780, 400, 780 + size), size=size)
        return Block([Line([w], w.bbox, text)], w.bbox, 1)

    assert lexicon_hits("Tel. 089 123 · Fax 089 456 · www.example.de") >= 2
    assert footer_score(blk("Vorstand: A · B · C", 7), 11, 30, False) >= 2.5
    assert footer_score(blk("und damit endet der Satz", 7), 11, 30, False) < 2.5


@pytest.mark.parametrize(
    "lines,numbered",
    [
        (["Eingegangen: 22.6.2021 / Ausgegeben: 25.6.2021\t1"], True),
        (["1"], True),
        (["Eingegangen: 22.6.2021 / Ausgegeben: 25.6.2021\t2"], False),
        (["Biberach\t12", "Bodenseekreis\t1"], False),
        (["40\t1"], False),
        (["Ausgegeben: 25.6.2021 1"], False),
        ([""], False),
    ],
    ids=["closing-cell", "lone", "other-page", "table", "number-row", "no-tab", "empty"],
)
def test_zone_page_number(lines, numbered):
    from pazufa_pdf_parser._pipeline.model import Block, Line, Word

    words = [Word(t, BBox(70, 780 + 10 * i, 400, 790 + 10 * i), size=10) for i, t in enumerate(lines)]
    block = Block([Line([w], w.bbox, w.text) for w in words], BBox.enclosing(w.bbox for w in words), 1)
    assert (zone_page_number([block], 1) is block) is numbered


def _pages(*furniture):
    """One page per (header, footer); a newline starts another line, a tab another cell 250 pt to the right.
    The body sits below the header band."""
    return [body(200) + _band(70, 40, head) + _band(280, 790, foot) for head, foot in furniture]


def _band(x, y, text):
    return [
        T(x + 250 * c, y + 12 * k, cell, 9)
        for k, ln in enumerate(text.splitlines())
        for c, cell in enumerate(ln.split("\t"))
    ]


@pytest.mark.parametrize(
    "furniture,printed",
    [
        ([("", "- 1 -"), ("", "- 2 -")], ["1", "2"]),
        ([("", "Seite 1 von 2"), ("", "Seite 2 von 2")], ["1", "2"]),
        ([("", "I"), ("", "II")], ["I", "II"]),
        ([("", "ll"), ("", "ll")], [None, None]),
        ([("Landtag – 19. Wahlperiode 1", ""), ("Landtag – 19. Wahlperiode 2", "")], ["1", "2"]),
        ([("178 Gesetzblatt Nr. 12/2025", ""), ("Gesetzblatt Nr. 12/2025 179", "")], ["178", "179"]),
        ([("178 Gesetzblatt", "Anlage 8"), ("Gesetzblatt 179", "Anlage 9")], ["178", "179"]),
        ([("Stellungnahme | Seite 1 von 2", ""), ("Stellungnahme | Seite 2 von 2", "")], ["1", "2"]),
        ([("2025\nLandtag Seite 1", ""), ("2025\nLandtag Seite 2", "")], ["1", "2"]),
        ([("Landtag Drucksache 17 / 273", "")] * 2, [None, None]),
        ([("Landtag – 19. Wahlperiode 5", ""), ("Landtag – 19. Wahlperiode 9", "")], [None, None]),
        ([("", "Telefon 0711 2063 0\nTelefax 0711 2063 1")] * 3, [None, None, None]),
        ([("", "Quelle: Statistisches Landesamt ²")] * 2, [None, None]),
        ([("", "80333 München"), ("", "80334 München")], [None, None]),
        ([("", "Recyclingpapier\tI"), ("", "II")], ["I", "II"]),
        ([("", "poststelle@lfv.de\t1 / 2"), ("", "2 / 2")], ["1", "2"]),
        ([("Bayerisches\t177", ""), ("178\tBayerisches", "")], ["177", "178"]),
        ([("Landtag\t5", ""), ("Landtag\t9", "")], [None, None]),
    ],
    ids=[
        "page-number-line",
        "seite-von",
        "roman",
        "ocr-misread-roman",
        "closing-header",
        "alternating-header",
        "header-before-footer",
        "seite-inside-header",
        "year-beside-seite",
        "constant-number",
        "not-consecutive",
        "phone-and-fax",
        "footnote-mark",
        "five-digit-number",
        "number-cell-beside-footer",
        "fraction-cell",
        "number-cell-beside-heading",
        "not-consecutive-cells",
    ],
)
def test_printed_page(furniture, printed):
    d = parse(make_pdf(_pages(*furniture)), NO_OCR)
    assert [p.printed_page for p in d.pages] == printed
    assert not d.report.issues


def test_page_number_cell_leaves_its_line():
    # PlPr 18/10 prints "I" in the gap of its two-column page-1 footer
    page = parse(make_pdf(_pages(("", "Recyclingpapier\tI"), ("", "II"))), NO_OCR).pages[0]
    assert [(b.kind, b.text) for b in page.blocks if b.kind.is_furniture] == [
        (BlockKind.FOOTER, "Recyclingpapier"),
        (BlockKind.PAGE_NUMBER, "I"),
    ]


@pytest.mark.parametrize(
    "number,gap,real_number,printed,in_body",
    [
        ("17/1076", 0, "910", "910", True),
        ("17/1076", 2.3, "910", "910", True),
        ("17/1076", 6.3, "910", "17", False),
        ("17/1076", 0, None, None, True),
        ("- 910 -", 0, None, "910", False),
    ],
    ids=[
        "wrapped-at-leading",
        "wrapped-with-ocr-gap",
        "below-a-page-number-gap",
        "no-other-page-number",
        "dashed-page-number-under-text",
    ],
)
def test_number_wrapped_from_the_line_above(number, gap, real_number, printed, in_body):
    # PlPr 17/19 p. 31: an agenda item's "– Drucksache" wraps its number "17/1076" into the bottom band (#45);
    # the protocol's tight leading makes the two line boxes overlap, OCR boxes leave ~1 pt; 5 pt below the text
    # (gap 6.3) is where real page numbers sit, so a wrap that far down still reads as one
    lines = [*PROSE[:2], "Gesetzes über die Grundsteuer (ÄndGLGrStG) – Drucksache", number]
    text = [replace(t, y=t.y + gap) if t.text == number else t for t in paragraph(70, 690, lines, 11, leading=1.0)]
    page = body(200) + text + ([T(70, 790, real_number, 9)] if real_number else [])
    d = parse(make_pdf([page]), NO_OCR)
    assert d.pages[0].printed_page == printed
    assert (number in d.pages[0].text()) is in_body


def _row(y, *cells):
    return [T(70 + 250 * c, y, cell, 11) for c, cell in enumerate(cells)]


@pytest.mark.parametrize(
    "pages,row,printed",
    [
        ([body(200) + _row(450, "Biberach", "1"), body(200) + [T(280, 790, "2", 9)]], "Biberach 1", [None, "2"]),
        (
            [
                body(200)
                + [T(70, 40, "Landtag – 18. Wahlperiode – Juli 2022", 9)]
                + (_row(745, "Haushaltsjahr", "2023") if i == 1 else [])
                for i in range(3)
            ],
            "Haushaltsjahr 2023",
            [None] * 3,
        ),
    ],
    ids=["table-row-mid-page", "year-beside-a-year-header"],
)
def test_number_cell_in_the_body_is_no_page_number(pages, row, printed):
    # the next page's number or a header year would continue the row's number
    d = parse(make_pdf(pages), NO_OCR)
    assert [p.printed_page for p in d.pages] == printed
    assert any(row in p.text() for p in d.pages)


def test_printed_page_of_an_empty_page():
    assert parse(make_pdf([[]]), NO_OCR).pages[0].printed_page is None


def test_printed_page_in_a_page_range():
    pdf = make_pdf(_pages(*[(f"Landtag – 19. Wahlperiode {n}", "") for n in (1, 2, 3)]))
    assert [p.printed_page for p in parse(pdf, replace(NO_OCR, first_page=2)).pages] == ["2", "3"]
    # one page alone: nothing shows the number counting up
    assert parse(pdf, replace(NO_OCR, last_page=1)).pages[0].printed_page is None


@pytest.mark.parametrize(
    "first_line,is_header",
    [
        ([T(70, 40, "Landtag von Baden-Württemberg", 9), T(400, 40, "Drucksache 17 / 273", 9)], True),
        ([T(70, 40, "19. Wahlperiode", 9), T(400, 40, "17.06.2026 Drucksache 17 / 273", 9)], True),
        ([T(70, 40, "Plenarprotokoll 17 / 273", 12)], True),
        ([T(70, 40, "Betreff:", 9), T(150, 40, "Drucksache 17 / 273", 9)], False),
        ([T(70, 40, "Bezug", 9), T(150, 40, "Antrag zu Drucksache 17 / 273", 9)], False),
        ([T(70, 40, "Landtag", 9), T(400, 40, "Drucksache 17 / 273 (neu)", 9)], False),
        ([T(70, 40, "Der Ausschuss empfiehlt die Annahme der Drucksache 17 / 273", 9)], False),
    ],
    ids=[
        "masthead",
        "masthead-with-date",
        "protocol-masthead",
        "email-field",
        "label-and-value",
        "number-with-suffix",
        "prose",
    ],
)
def test_single_page_masthead_is_furniture(first_line, is_header):
    # one page has no running header to repeat it; the document's own number still marks it
    page = parse(make_pdf([first_line + body(200)]), NO_OCR).pages[0]
    assert ("17 / 273" in page.furniture_text()) is is_header
    assert ("17 / 273" in page.text()) is not is_header


_GAZETTE = "Gesetzblatt für Baden-Württemberg, Jahrgang 2026, Nr. 12 vom 27. Februar 2026"


@pytest.mark.parametrize(
    "top,is_header",
    [
        ([T(98, 40, _GAZETTE, 13)], True),
        ([T(70, 40, f"{_GAZETTE} verkündet und wie folgt geändert:", 9)], False),  # fits the page width
        ([T(70, 40, "Anlage", 13), T(98, 58, _GAZETTE, 13)], False),
    ],
    ids=["running-header", "citation", "below-the-first-line"],
)
def test_gazette_header_printed_once_is_furniture(top, is_header):
    # a two-page Gesetzblatt issue prints its running header on page 2 only, so nothing repeats it
    page = parse(make_pdf([body(200), top + body(200)]), NO_OCR).pages[1]
    header = top[-1].text
    assert (header in page.furniture_text()) is is_header
    assert (header in page.text()) is not is_header


def test_masthead_only_on_the_first_page():
    # an agenda item at the top of a later page cites its Drucksache the same way
    item = [T(70, 40, "Gesetzentwurf der Staatsregierung", 9), T(400, 40, "Drucksache 17 / 273", 9)]
    d = parse(make_pdf([body(200), item + body(200)]), NO_OCR)
    assert "17 / 273" in d.text() and d.pages[1].furniture_text() == ""


def test_step_order():
    assert Pipeline().names() == ["extract", "layout", "garbled", "furniture", "page_numbers", "sanitize", "flow"]
