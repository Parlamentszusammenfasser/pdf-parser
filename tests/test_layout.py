"""Layout analysis on synthetic word geometry (no PDF involved)."""

from pazufa_pdf_parser._pipeline.layout.blocks import classify_headings, split_blocks, starts_with_marker
from pazufa_pdf_parser._pipeline.layout.furniture import detect_furniture, is_page_number, normalize_key
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

    def test_page_number_patterns(self):
        for t in ["3", "- 3 -", "Seite 3", "Seite 3 von 10", "3 / 10", "S. 4", "ii", "XIV"]:
            assert is_page_number(t), t
        for t in ["§ 3", "Seite drei", "Kapitel 3", "ll", "IIII", "C"]:
            assert not is_page_number(t)

    def test_normalize_key(self):
        assert normalize_key("Seite 12 von 30") == normalize_key("Seite 3 von 30")
