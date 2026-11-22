"""Layout analysis on synthetic word geometry (no PDF involved)."""

import pytest

from pazufa_pdf_parser._pipeline.layout.blocks import classify_headings, fill_leaves, split_blocks, starts_with_marker
from pazufa_pdf_parser._pipeline.layout.furniture import (
    detect_furniture,
    is_page_number,
    normalize_key,
    page_number_value,
)
from pazufa_pdf_parser._pipeline.layout.lines import build_lines
from pazufa_pdf_parser._pipeline.layout.segment import Segmenter, detect_synopsis
from pazufa_pdf_parser._pipeline.model import BBox, BlockKind, Page, RegionKind, Word


def words_for(x, y, text, size=10.0, bold=False, char_w=None):
    """Words of a text line starting at (x, y) with a crude width model."""
    char_w = char_w or size * 0.5
    out = []
    cx = x
    for tok in text.split():
        w = len(tok) * char_w
        out.append(Word(tok, BBox(cx, y, cx + w, y + size), size=size, bold=bold))
        cx += w + size * 0.28
    return out


def lines_block(x, y, lines, size=10.0, leading=1.3, **kw):
    out = []
    for i, ln in enumerate(lines):
        out += words_for(x, y + i * size * leading, ln, size, **kw)
    return out


PROSE = [
    "Dies ist ein längerer Absatz mit mehreren Zeilen Text, der",
    "über die ganze Breite der Spalte läuft und daher fortlaufend",
    "gelesen werden muss, ohne dass Spalten erkannt werden.",
]


class TestLines:
    def test_words_grouped_by_baseline(self):
        ws = words_for(50, 100, "erste Zeile hier") + words_for(50, 113, "zweite Zeile")
        lines = build_lines(ws)
        assert [ln.text for ln in lines] == ["erste Zeile hier", "zweite Zeile"]

    def test_superscript_stays_on_line(self):
        ws = words_for(50, 100, "Fußnote im Text")
        ws.append(Word("1", BBox(140, 97, 144, 103), size=6))
        lines = build_lines(ws)
        assert len(lines) == 1
        assert lines[0].text.endswith("1")

    def test_large_gap_becomes_tab(self):
        ws = words_for(50, 100, "Berichterstatter:") + words_for(250, 100, "Christian Hierneis")
        assert build_lines(ws)[0].text == "Berichterstatter:\tChristian Hierneis"

    def test_skewed_scan_line(self):
        ws = [Word(f"w{i}", BBox(50 + i * 40, 100 + i * 0.8, 80 + i * 40, 110 + i * 0.8), size=10) for i in range(10)]
        assert len(build_lines(ws)) == 1


class TestSegmentation:
    def seg(self, words, w=595, h=842):
        return Segmenter(w, h).segment(words)

    def test_single_column_is_one_leaf(self):
        region = self.seg(lines_block(70, 100, PROSE))
        assert region.kind is RegionKind.LEAF

    def test_two_columns_detected_and_read_left_first(self):
        left = lines_block(
            60,
            100,
            [
                "linke Spalte Zeile eins",
                "linke Spalte Zeile zwei",
                "linke Spalte Zeile drei",
                "linke Spalte Zeile vier",
            ],
        )
        right = lines_block(
            330,
            100,
            [
                "rechte Spalte Zeile eins",
                "rechte Spalte Zeile zwei",
                "rechte Spalte Zeile drei",
                "rechte Spalte Zeile vier",
            ],
        )
        region = self.seg(left + right)
        cols = [r for r in region.iter_regions() if r.kind is RegionKind.COLUMNS]
        assert cols, "columns expected"
        from pazufa_pdf_parser._pipeline.layout.blocks import fill_leaves

        fill_leaves(region, 1)
        text = " ".join(b.raw_text for b in region.iter_blocks())
        assert text.index("linke Spalte Zeile vier") < text.index("rechte Spalte Zeile eins")

    def test_full_width_heading_above_columns(self):
        title = words_for(60, 60, "Eine Überschrift über beide Spalten hinweg reicht weit nach rechts hinaus", 14)
        left = lines_block(
            60, 100, ["linke Spalte mit Text eins", "linke Spalte mit Text zwei", "linke Spalte mit Text drei"]
        )
        right = lines_block(
            330, 100, ["rechte Spalte mit Text eins", "rechte Spalte mit Text zwei", "rechte Spalte mit Text drei"]
        )
        region = self.seg(title + left + right)
        assert region.kind is RegionKind.STACK
        assert region.children[0].kind is RegionKind.LEAF
        assert any(r.kind is RegionKind.COLUMNS for r in region.children)

    def test_key_value_rows_are_not_columns(self):
        ws = []
        for i, (k, v) in enumerate(
            [("Von:", "Thomas Schmid"), ("An:", "Referat B6"), ("Betreff:", "Anhörung"), ("Datum:", "6. März 2025")]
        ):
            ws += words_for(70, 100 + i * 13, k) + words_for(170, 100 + i * 13, v)
        region = self.seg(ws)
        assert not any(r.kind is RegionKind.COLUMNS for r in region.iter_regions())

    def test_list_markers_are_not_a_column(self):
        ws = []
        for i, item in enumerate(["unverändert", "unverändert", "unverändert"]):
            ws += words_for(320, 100 + i * 14, f"{'abc'[i]})") + words_for(420, 100 + i * 14, item)
        region = self.seg(ws)
        assert not any(r.kind is RegionKind.COLUMNS for r in region.iter_regions())

    def test_letter_sidebar_is_aside_read_first(self):
        address = lines_block(
            70,
            150,
            ["Bayerische Staatskanzlei", "Frau Staatsrätin Muster", "Franz-Josef-Strauß-Ring 1", "80539 München"],
            11,
        )
        sidebar = lines_block(
            440,
            140,
            [
                "Verband der Testbetriebe e.V.",
                "Musterweg 5",
                "80331 München",
                "Telefon 089 123456-0",
                "Telefax 089 123456-99",
                "info@testverband.de",
            ],
            8,
        )
        body = lines_block(70, 300, PROSE, 11, char_w=4.2)
        region = self.seg(address + sidebar + body)
        cols = [r for r in region.iter_regions() if r.kind is RegionKind.COLUMNS]
        assert cols and cols[0].aside_first
        from pazufa_pdf_parser._pipeline.layout.blocks import fill_leaves

        fill_leaves(region, 1)
        order = [b.raw_text.split("\n")[0] for b in region.iter_blocks()]
        assert order[0].startswith("Verband")  # sidebar first
        assert order[-1].startswith("Dies ist")  # body last

    @pytest.mark.parametrize(
        "rows,right_size,aside",
        [
            ([("Strobl", "Dr. Bayaz"), ("Dr. Hoffmeister-Kraut", "Olschowski"), ("Gentges", "Lucha")], 14, False),
            (
                [
                    ("Landtag von Bayern", "Ihr Zeichen: AB 12"),
                    ("Herrn Max Mustermann", "Datum: 03.03.2026"),
                    ("Maximilianeum", "Telefon 089 1234"),
                    ("81627 München", "Bearbeiter: Huber"),
                ],
                10,
                True,
            ),
        ],
        ids=["signature-lists", "address-beside-smaller-sidebar"],
    )
    def test_columns_pairing_up_line_for_line(self, rows, right_size, aside):
        # Gesetzblatt ministers sign in two lists read left first; a letter's sidebar aligned with the
        # address field stays a sidebar
        ws = [
            w
            for i, (a, b) in enumerate(rows)
            for w in words_for(100, 190 + 18 * i, a, 14) + words_for(420, 190 + 18 * i, b, right_size)
        ]
        region = self.seg(ws)
        cols = [r for r in region.iter_regions() if r.kind is RegionKind.COLUMNS]
        assert cols and cols[0].aside_first is aside

    def test_synopsis_detection(self):
        txt = [
            "Artikel 1 Änderung des Stiftungsgesetzes",
            "Das Stiftungsgesetz vom 30. Mai 2023",
            "wird wie folgt geändert: In § 6 werden",
            "die Wörter gestrichen und ersetzt.",
        ]
        right = list(txt)
        right[3] = "die Wörter gestrichen. (unverändert)"
        region = self.seg(lines_block(60, 100, txt) + lines_block(320, 100, right))
        from pazufa_pdf_parser._pipeline.layout.blocks import fill_leaves

        fill_leaves(region, 1)
        detect_synopsis(region, lambda r: " ".join(b.raw_text for b in r.iter_blocks()))
        assert any(r.synopsis for r in region.iter_regions())

    def test_different_columns_are_not_synopsis(self):
        left = lines_block(
            60,
            100,
            [
                "Haushalt und Finanzen der Gemeinde",
                "werden jährlich neu beschlossen und",
                "vom Rat in öffentlicher Sitzung beraten",
            ],
        )
        right = lines_block(
            320,
            100,
            [
                "Sportverein meldet neue Mitglieder",
                "Training jeden Dienstag im Freibad",
                "Anmeldung beim Vorstand möglich",
            ],
        )
        region = self.seg(left + right)
        from pazufa_pdf_parser._pipeline.layout.blocks import fill_leaves

        fill_leaves(region, 1)
        detect_synopsis(region, lambda r: " ".join(b.raw_text for b in r.iter_blocks()))
        assert not any(r.synopsis for r in region.iter_regions())

    def test_empty_input(self):
        region = self.seg([])
        assert list(region.iter_blocks()) == []

    @pytest.mark.parametrize("footer_lines", [2, 1], ids=["two-column-footer", "single-tabbed-row"])
    def test_footer_columns_below_a_margin_page_number(self, footer_lines):
        # BW page 1: the masthead date and the page number "1" open a right-margin gap down the whole page
        masthead = words_for(70, 60, "17. Wahlperiode") + words_for(400, 60, "22.6.2021")
        row = words_for(70, 700, "Eingegangen: 22.6.2021 / Ausgegeben: 25.6.2021") + words_for(515, 698, "1", 14)
        left = ["Drucksachen sind im Internet", "abrufbar unter: www.example.de"][:footer_lines]
        right = ["Der Landtag druckt auf Recycling-", "papier mit dem Blauen Engel."][:footer_lines]
        footer = lines_block(70, 716, left, 9, leading=1.0) + lines_block(300, 716, right, 9, leading=1.0)
        region = self.seg(masthead + lines_block(70, 100, PROSE) + row + footer)
        fill_leaves(region, 1)
        columns = [r for r in region.iter_regions() if r.kind is RegionKind.COLUMNS]
        assert len(columns) == footer_lines - 1  # one row with a tab is not a column pair
        if columns:
            assert [b.raw_text.split("\n")[0] for b in columns[0].iter_blocks()] == [left[0], right[0]]


class TestBlocks:
    def test_paragraph_gap_splits(self):
        lines = build_lines(lines_block(70, 100, PROSE) + lines_block(70, 160, PROSE))
        blocks = split_blocks(lines, 1)
        assert len(blocks) == 2

    def test_list_items_split(self):
        lines = build_lines(
            lines_block(70, 100, ["Einleitung zum Thema:", "1. Erster Punkt", "2. Zweiter Punkt", "a) Unterpunkt"])
        )
        blocks = split_blocks(lines, 1)
        assert [b.kind for b in blocks] == [
            BlockKind.PARAGRAPH,
            BlockKind.LIST_ITEM,
            BlockKind.LIST_ITEM,
            BlockKind.LIST_ITEM,
        ]

    def test_wrapped_date_is_not_list_item(self):
        lines = build_lines(
            lines_block(70, 100, ["Der Ausschuss hat in seiner Sitzung am", "17. Juli 2025 beraten und beschlossen."])
        )
        blocks = split_blocks(lines, 1)
        assert len(blocks) == 1

    def test_font_change_splits_heading(self):
        ws = words_for(70, 100, "Überschrift", 16, bold=True) + lines_block(70, 122, PROSE)
        blocks = split_blocks(build_lines(ws), 1)
        assert len(blocks) == 2
        classify_headings(blocks, 10.0)
        assert blocks[0].kind is BlockKind.HEADING and blocks[0].level == 1
        assert blocks[1].kind is BlockKind.PARAGRAPH

    @pytest.mark.parametrize(
        "words,blocks",
        [
            (
                words_for(70, 100, "Information über Staats-", bold=True)
                + words_for(70, 113, "vertragsentwürfe; hier"),
                1,
            ),
            (words_for(70, 100, "Information über Staats-", 13) + words_for(70, 114, "vertragsentwürfe; hier"), 1),
            (
                words_for(70, 100, "Information über Staats\u2010", bold=True) + words_for(70, 113, "vertragsentwürfe"),
                1,
            ),
            (
                words_for(70, 100, "für Digitalisierung und Europa Ma-")
                + words_for(70, 113, "nuel Hagel:", bold=True)
                + words_for(130, 113, "Frau Präsidentin!"),
                1,
            ),
            (words_for(70, 100, "Information über Staats -", bold=True) + words_for(70, 113, "vertragsentwürfe"), 2),
            (words_for(70, 100, "Information über Staats-", bold=True) + words_for(70, 140, "vertragsentwürfe"), 2),
            (words_for(300, 100, "Verwaltungs-") + words_for(70, 113, "aufgaben des Landes"), 2),
            (words_for(70, 100, "a) Vor-") + words_for(70, 113, "b) Nachname"), 2),
        ],
        ids=[
            "bold-change",
            "size-change",
            "unicode-hyphen",
            "speaker-label",
            "dash",
            "paragraph-gap",
            "side-by-side",
            "list-markers",
        ],
    )
    def test_hyphenated_word_keeps_a_style_change_in_one_block(self, words, blocks):
        # a protocol ToC entry switches from its bold title to regular text inside a hyphenated word
        assert len(split_blocks(build_lines(words), 1)) == blocks

    def test_split_blocks_without_lines(self):
        assert split_blocks([], 1) == []

    def test_run_in_speaker_label_starts_block(self):
        ws = words_for(70, 100, "Präsidentin Aigner:", bold=True) + words_for(170, 100, "Das Wort hat Herr Huber.")
        ws += words_for(70, 113, "Martin Huber (CSU):", bold=True) + words_for(175, 113, "Danke schön.")
        blocks = split_blocks(build_lines(ws), 1)
        assert len(blocks) == 2

    def test_marker_detection(self):
        assert starts_with_marker("1. Punkt")
        assert starts_with_marker("aa) Unterpunkt")
        assert starts_with_marker("(2) Absatz")
        assert starts_with_marker("§ 3 Inkrafttreten")
        assert starts_with_marker("• Aufzählung")
        assert not starts_with_marker("17. Juli 2025")
        assert not starts_with_marker("19. Wahlperiode")
        assert not starts_with_marker("Normaler Text")


class TestFurniture:
    def page(self, n, header, footer=None, body="Inhalt der Seite mit Text"):
        p = Page(number=n, width=595, height=842)
        ws = words_for(70, 30, header) + words_for(70, 300, body + f" {n}")
        if footer:
            ws += words_for(280, 810, footer)
        p.words = ws
        p.lines = build_lines(ws)
        return p

    def test_running_header_and_page_numbers(self):
        pages = [self.page(i, f"Drucksache 19/1234 Bayerischer Landtag Seite {i}", str(i)) for i in range(1, 4)]
        furn = detect_furniture(pages)
        kinds = {(pi, k) for (pi, _), k in furn.items()}
        assert (0, BlockKind.HEADER) in kinds and (2, BlockKind.HEADER) in kinds
        assert (1, BlockKind.PAGE_NUMBER) in kinds
        # body lines are never furniture
        for (pi, li), _ in furn.items():
            assert "Inhalt" not in pages[pi].lines[li].text

    def test_alternating_headers(self):
        pages = [
            self.page(1, "Drucksache 20/3769 Landtag – 20. Wahlperiode"),
            self.page(2, "Landtag – 20. Wahlperiode Drucksache 20/3769"),
        ]
        assert len(detect_furniture(pages)) == 2

    def test_single_page_keeps_header(self):
        pages = [self.page(1, "Einmaliger Briefkopf der Firma")]
        assert detect_furniture(pages) == {}

    @pytest.mark.parametrize(
        "text,number,is_number",
        [
            ((300, 60, "– Drucksache"), (300, 68, "17/1076"), False),
            ((300, 784, "Ende der rechten Spalte"), (45, 792, "910"), True),
            ((290, 50, "rw", 30), (300, 60, "4"), True),
            (None, (280, 810, "910"), True),
        ],
        ids=["wrap-under-header", "beside-other-column", "inside-a-taller-line", "nothing-above"],
    )
    def test_number_overlapping_the_line_above(self, text, number, is_number):
        # line boxes overlap at a protocol's tight leading; page numbers sit below a gap (#45);
        # "- 9 -" is the page's real page number; an OCR'd logo ("rw") can enclose a number
        ws = words_for(*number) + (words_for(*text) if text else []) + words_for(280, 20, "- 9 -")
        p = Page(number=1, width=595, height=842, words=ws, lines=build_lines(ws))
        kinds = {p.lines[li].text: k for (_, li), k in detect_furniture([p]).items()}
        assert (kinds.get(number[2]) is BlockKind.PAGE_NUMBER) is is_number

    def test_page_number_patterns(self):
        for t in ["3", "- 3 -", "Seite 3", "Seite 3 von 10", "3 / 10", "S. 4", "ii", "XIV"]:
            assert is_page_number(t), t
        for t in ["§ 3", "Seite drei", "Kapitel 3", "ll", "IIII", "C"]:
            assert not is_page_number(t)

    def test_normalize_key(self):
        assert normalize_key("Seite 12 von 30") == normalize_key("Seite 3 von 30")


@pytest.mark.parametrize(
    "text,value",
    [
        ("- 3 -", 3),
        ("3 / 10", 3),
        ("Seite 12 von 30", 12),
        ("II", 2),
        ("xiv", 14),
        ("ll", None),
        ("§ 3", None),
        ("", None),
    ],
    ids=["dashes", "of-total", "seite", "roman", "roman-subtractive", "ocr-ll", "paragraph", "empty"],
)
def test_page_number_value(text, value):
    assert page_number_value(text) == value
