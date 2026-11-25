"""Ruled tables: rows and cells come from the table's border lines (#47)."""

import time

import pytest

from conftest import NO_OCR
from pazufa_pdf_parser import parse
from pazufa_pdf_parser._pipeline.layout.segment import _table_rules
from pazufa_pdf_parser._pipeline.model import BBox
from pdfgen import Rule, T, make_pdf, paragraph


def grid(xs, ys, w=0.5):
    return [Rule(xs[0], y, xs[-1], y + w) for y in ys] + [Rule(x, ys[0], x + w, ys[-1]) for x in xs]


def texts(items):
    d = parse(make_pdf([items]), NO_OCR)
    assert not d.report.issues
    return [b.text for b in d.pages[0].blocks]


# gutters of 6 pt, narrower than one em, like the BW Anhörung synopsis of Drs. 18/623
XS = [60, 121, 233.6, 376.2, 507.3]


def cell(col, y, lines, bold=False):
    return paragraph(XS[col] + 3, y, lines, 9, bold=bold)


ANHOERUNG = [
    *paragraph(
        60, 60, ["Übersicht über die von den Verbänden im Anhörungsverfahren vorgetragenen Anliegen"], 11, bold=True
    ),
    *[t for i, h in enumerate(["Verband", "Anliegen", "Begründung", "Votum"]) for t in cell(i, 100, [h], True)],
    *cell(0, 117, ["Beamtenbund"]),
    *cell(1, 117, ["Lineare Erhöhung um 3,19", "Prozent ab 1. April 2026."]),
    *cell(
        2,
        117,
        ["Der in der Tarifeinigung vom", "14. Februar 2026 vereinbarte Min-", "destbetrag müsse übertragen", "werden."],
    ),
    *cell(3, 117, ["Der Gesetzentwurf hat aus-", "schließlich den Tarifübertrag", "zum Gegenstand."]),
    *[t for i, c in enumerate(["Städtetag", "Stellen", "im Haushalt 2026", "12"]) for t in cell(i, 170, [c])],
    *[t for i, c in enumerate(["für Kreise", "Stellen", "im Haushalt 2027", "4"]) for t in cell(i, 187, [c])],
    *grid(XS, [96, 113, 166, 183, 200]),
]


@pytest.mark.parametrize(
    "placed",
    [{}, {"rotate": 90}, {"form": (0.9, 0, 0, 0.9, 20, 40)}],
    ids=["upright", "rotated", "form-xobject"],
)
def test_table_read_row_by_row_each_cell_whole(placed):
    # a row of one-line cells stays one line, and rows never join as one paragraph ("12" / "für Kreise")
    d = parse(make_pdf([ANHOERUNG], **placed), NO_OCR)
    assert [b.text for b in d.pages[0].blocks] == [
        "Übersicht über die von den Verbänden im Anhörungsverfahren vorgetragenen Anliegen",
        "Verband Anliegen Begründung Votum",
        "Beamtenbund",
        "Lineare Erhöhung um 3,19 Prozent ab 1. April 2026.",
        "Der in der Tarifeinigung vom 14. Februar 2026 vereinbarte Mindestbetrag müsse übertragen werden.",
        "Der Gesetzentwurf hat ausschließlich den Tarifübertrag zum Gegenstand.",
        "Städtetag Stellen im Haushalt 2026 12",
        "für Kreise Stellen im Haushalt 2027 4",
    ]


def test_cell_merged_over_sub_rows_stays_whole():
    # BY Gesetzblatt Anlage: the sub-row border runs only under the second column, which Word draws
    # with a column border in one piece per sub-row
    items = [
        *paragraph(63, 105, ["Anatomie und", "Physiologie"], 9),
        *paragraph(163, 103, ["240"], 9),
        *paragraph(163, 120, ["60"], 9),
        Rule(60, 100, 260, 100.5),
        Rule(160, 115.5, 260, 116),
        Rule(60, 140, 260, 140.5),
        Rule(60, 100, 60.5, 140.5),
        Rule(160, 100, 160.5, 115.5),
        Rule(160, 116, 160.5, 140.5),
        Rule(260, 100, 260.5, 140.5),
    ]
    assert texts(items) == ["Anatomie und\nPhysiologie", "240", "60"]


# every line ends a sentence, so the flow step cannot join a wrongly cut paragraph again
PROSE = [
    "Die Landesregierung legt den Entwurf eines Gesetzes vor.",
    "Er passt die Besoldung an die Tarifeinigung an.",
    "Er setzt die Vorgaben des Verfassungsgerichts um.",
    "Die Alimentation bleibt damit amtsangemessen.",
]
LINE_TOP = [100 + i * 11 * 1.35 for i in range(4)]
BETWEEN_2_AND_3 = (LINE_TOP[1] + 11 + LINE_TOP[2]) / 2


@pytest.mark.parametrize(
    "rules",
    [
        # BY Tagesordnung frames a note ("Sitzungsablauf auf Seite 5")
        grid([55, 400], [BETWEEN_2_AND_3, LINE_TOP[3] + 14]),
        [Rule(60, LINE_TOP[0] + 11.5, 330, LINE_TOP[0] + 12)],
        [
            *grid([420, 480, 540], [LINE_TOP[0] - 3, BETWEEN_2_AND_3, LINE_TOP[3] + 14]),
            *[t for x, y, v in [(423, 100, "12"), (483, 100, "34"), (423, 135, "56")] for t in paragraph(x, y, [v])],
        ],
        # the column borders of a table under the paragraph run nowhere beside it (Drs. 18/623 p. 20)
        [
            *grid([60, 150, 250, 330], [LINE_TOP[3] + 20, LINE_TOP[3] + 36, LINE_TOP[3] + 52]),
            *[
                t
                for x, v in [(63, "A 7"), (153, "511,38"), (253, "493,74")]
                for t in paragraph(x, LINE_TOP[3] + 23, [v])
            ],
        ],
    ],
    ids=["frame", "underline", "table-beside", "table-below"],
)
def test_rules_that_are_no_row_border_keep_a_paragraph_whole(rules):
    assert " ".join(PROSE) in texts(paragraph(60, 100, PROSE) + rules)


def test_table_closing_the_page_is_no_footer():
    # 17/1104 p. 36 ends on a small table of budget figures, whose one-line rows score like footer lines
    rows = [("2021", "2022"), ("3.000,0", "3.000,0")]
    table = [
        t for i, row in enumerate(rows) for x, v in zip((70, 150), row) for t in paragraph(x, 758 + 14 * i, [v], 7)
    ]
    d = parse(make_pdf([paragraph(60, 670, PROSE) + table + grid([65, 140, 220], [755, 769, 783])]), NO_OCR)
    assert "2021 2022" in d.text()
    assert "3.000,0 3.000,0" in d.text()


def test_text_between_tables_keeps_its_paragraphs():
    # 17/1104 p. 36: a title over items that each end in a small table; cut off by the tables, the title's own
    # spaced-out lines would pass for the leading and run on into one paragraph
    items = [
        *paragraph(250, 100, ["Übersicht"], 10, bold=True),
        *paragraph(210, 125, ["über die Förderung des Schulhausbaus"], 9, bold=True),
        *paragraph(110, 150, ["Beratungen des Finanzausschusses", "über den Einzelplan 04"], 9, bold=True),
        *paragraph(110, 190, ["Kap. 0402", "Allgemeine Bewilligungen", "Tit. Gr. 91"], 9),
    ]
    for y in (240, 340):
        items += paragraph(110, y, ["Tit. 883 91A Zuweisungen an kommunale Träger"], 9, bold=True)
        items += paragraph(125, y + 22, ["Planansätze in Tsd. EUR:"], 9)
        items += [
            T(x, y + dy, v, 7)
            for x, dy, v in [(330, 30, "2021"), (410, 30, "2022"), (330, 42, "1,0"), (410, 42, "2,0")]
        ]
        items += grid([300, 380, 460], [y + 28, y + 40, y + 52])
    assert texts(items)[:4] == [
        "Übersicht",
        "über die Förderung des Schulhausbaus",
        "Beratungen des Finanzausschusses\nüber den Einzelplan 04",
        "Kap. 0402\nAllgemeine Bewilligungen\nTit. Gr. 91",
    ]


def test_map_hatching_is_no_table():
    # a Bebauungsplan map hatched in thousands of separate strokes; joining them pairwise takes seconds
    strokes = [BBox(x, y, x + 3, y + 0.3) for x in range(0, 600, 6) for y in range(0, 800, 20)]
    start = time.perf_counter()
    assert _table_rules(strokes) == []
    assert time.perf_counter() - start < 0.5


def test_table_without_text():
    assert texts(grid([60, 200, 340], [100, 120, 140])) == []
