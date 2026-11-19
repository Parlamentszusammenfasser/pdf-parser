"""Second-pass footer detection (layout.footers) and the furniture/flow steps."""

from conftest import NO_OCR
from pazufa_pdf_parser import BlockKind, parse, render
from pazufa_pdf_parser._pipeline.extract.pdf import plausible_size
from pazufa_pdf_parser._pipeline.layout.footers import footer_score, lexicon_hits
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
    assert "nur bei voller Belegung" in d.text(pages=[1]) and d.text(pages=[2]) == ""  # owned by its first page
    assert "1 Bertelsmann Stiftung" in txt


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


def test_step_order():
    assert Pipeline().names() == ["extract", "layout", "furniture", "sanitize", "flow"]
