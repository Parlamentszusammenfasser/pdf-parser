"""End-to-end behaviour on synthetic PDFs (text layer)."""

import io
import subprocess

import pytest

from conftest import HAS_QPDF
from pazufa_pdf_parser import (
    BlockKind,
    DocType,
    FuncStep,
    OcrMode,
    PageSource,
    ParseOptions,
    PdfOpenError,
    Pipeline,
    StepError,
    parse,
    render,
    step,
)
from pdfgen import T, make_pdf, paragraph


class TestDispatch:
    def test_letter(self, parsed):
        d = parsed["letter"]
        assert d.doc_type is DocType.LETTER
        assert d.classification.subtype == "statement"
        f = d.fields["letter"]
        assert f["salutation"] == "Sehr geehrte Frau Muster,"
        assert f["closing"] == "Mit freundlichen Grüßen"
        assert f["signatory"]["name"] == "Dr. Max Mustermann"
        assert f["signatory"]["role"] == "Hauptgeschäftsführer"
        assert f["recipient"]["postal_code"] == "80535"
        assert f["recipient"]["lines"][0] == "Bayerisches Staatsministerium"
        assert f["return_address"][0] == "Verband der Testbetriebe e.V."
        assert f["date"] == "2024-07-16" and f["place"] == "München"
        assert f["subject"] == "Stellungnahme zum Entwurf eines Testgesetzes"
        assert f["sender"]["email"] == "info@testverband.de"
        assert d.fields["title"] == f["subject"]
        assert "print" not in d.fields and "email" not in d.fields  # not dispatched
        assert d.entities["ibans"][0]["valid"]

    def test_letter_text_quality(self, parsed):
        txt = render(parsed["letter"], "txt")
        assert "Änderung des Testgesetzes" in txt  # de-hyphenated across lines
        assert "einigen Punkten" in txt
        assert "berücksichtigt werden könnten" in txt
        assert "- 2 -" not in txt  # page number removed
        assert "Registergericht" not in txt  # repeating footer removed
        # paragraph continued across the page break is not glued to the closing
        assert "\n\nMit freundlichen Grüßen" in txt

    def test_bill(self, parsed):
        d = parsed["bill"]
        assert d.doc_type is DocType.PARLIAMENTARY_PRINT and d.classification.subtype == "bill"
        f = d.fields["print"]
        assert f["number"] == "19/1234" and f["period"] == 19
        assert f["parliament"] == "Bayerischer Landtag"
        assert f["date"] == "2025-02-01"
        assert f["title"] == "zur Änderung des Bayerischen Testgesetzes"
        assert f["originator"] == "Staatsregierung"
        secs = [n for n in d.legal if n.kind == "section"]
        assert [s.num for s in secs] == ["1", "2"]
        assert secs[0].heading == "Änderung des Testgesetzes"
        assert secs[1].heading == "Inkrafttreten"
        assert [p.num for p in secs[1].children] == ["1", "2"]
        # the explanation (Begründung) is not part of the law text
        assert not any("Entbürokratisierung" in t for n in d.legal for x in n.walk() for t in x.text)
        assert "Seite 2" not in render(d, "txt")

    def test_email(self, parsed):
        d = parsed["email"]
        assert d.doc_type is DocType.EMAIL
        e = d.fields["email"]
        assert e["from"] == {"name": "Thomas Schmid", "email": "t.schmid@example.org"}
        assert [a["email"] for a in e["to"]] == ["referat@stk.example.de", "a.bauer@example.de"]
        assert e["attachments"] == ["Stellungnahme.pdf", "Gesetzentwurf.pdf"]
        assert e["subject_clean"] == "Verbandsanhörung - Drittes Modernisierungsgesetz"
        assert e["salutation"] == "Sehr geehrter Herr Dr. Hirschberg,"
        assert e["signatory"]["name"] == "Thomas Schmid"
        assert len(e["thread"]) == 1 and e["thread"][0]["from"]["email"] == "vertretung@stk.example.de"

    def test_protocol(self, parsed):
        d = parsed["protocol"]
        assert d.doc_type is DocType.PLENARY_PROTOCOL
        p = d.fields["protocol"]
        assert p["session"] == 41 and p["date"] == "2025-02-04" and p["period"] == 19
        assert p["referenced_prints"] == ["19/4721"]
        names = [s.speaker for s in d.speeches]
        assert names == ["Ilse Aigner", "Albert Füracker", "Ilse Aigner", "Andreas Winhart", "Ilse Aigner"]
        assert d.speeches[1].role.startswith("Staatsminister")
        assert d.speeches[3].party == "AfD"
        # speech continues across the page break, interjection kept
        assert any("lehnen ihn daher ab" in t for t in d.speeches[3].paragraphs)
        assert "(Beifall bei der AfD)" in d.speeches[3].paragraphs

    def test_judgment(self, parsed):
        d = parsed["judgment"]
        assert d.doc_type is DocType.COURT_DECISION and d.classification.subtype == "judgment"
        c = d.fields["court"]
        assert c["court"] == "Verwaltungsgericht München"
        assert c["file_number"] == "M 8 K 20.1234"
        assert c["date"] == "2024-03-12"
        assert c["sections"] == ["tenor", "facts", "reasons", "remedies"]
        assert {p["role"] for p in c["parties"]} == {"Kläger", "Beklagter"}
        assert c["subject"] == "Baugenehmigung"

    def test_contract(self, parsed):
        d = parsed["contract"]
        assert d.doc_type is DocType.CONTRACT
        c = d.fields["contract"]
        assert c["title"] == "Mietvertrag"
        assert [p["role"] for p in c["parties"]] == ["Vermieterin", "Mieter"]
        assert c["parties"][0]["name"].startswith("Erika Musterfrau")
        assert [n.heading for n in d.legal if n.kind == "section"] == ["Vertragsgegenstand", "Mietzeit", "Kündigung"]

    def test_synopsis(self, parsed):
        d = parsed["synopsis"]
        assert d.doc_type is DocType.PARLIAMENTARY_PRINT and d.classification.subtype == "report"
        assert d.classification.features["has_synopsis"]
        syn = d.synopsis[0]
        assert syn["left_label"] == "Gesetzentwurf der Fraktionen"
        assert syn["right_label"] == "Ausschussvorschlag"
        left, right = syn["left"][0], syn["right"][0]
        assert left.kind == right.kind == "article"
        assert [c.num for c in left.children] == ["1", "2"] == [c.num for c in right.children]
        assert right.children[0].children[1].text == ["unverändert"]
        assert d.fields["print"]["parliament"] == "Schleswig-Holsteinischer Landtag"

    def test_two_column_reading_order(self, parsed):
        txt = render(parsed["two_column"], "txt")
        assert txt.index("vor der rechten Spalte gelesen werden muss.") < txt.index("Völlig anderer Inhalt")
        assert txt.index("im kommenden Haushaltsjahr.") < txt.index("Ein abschließender Absatz")
        # the column paragraph is reflowed into one line
        assert "Die erste Spalte beginnt mit einem Satz, der über mehrere Zeilen läuft" in txt


class TestRobustness:
    def test_bytes_path_and_fileobj_inputs(self, tmp_path, letter_pdf):
        p = tmp_path / "x.pdf"
        p.write_bytes(letter_pdf)
        a = parse(p, ocr="never")
        b = parse(str(p), ocr="never")
        c = parse(io.BytesIO(letter_pdf), ocr="never")
        assert a.sha256 == b.sha256 == c.sha256
        assert a.source == str(p) and c.source is None
        assert render(a, "txt") == render(c, "txt")

    def test_not_a_pdf(self):
        with pytest.raises(PdfOpenError, match="not a PDF"):
            parse(b"hello world")

    def test_empty_input(self):
        with pytest.raises(PdfOpenError, match="empty"):
            parse(b"")

    def test_missing_file(self, tmp_path):
        with pytest.raises(PdfOpenError):
            parse(tmp_path / "nope.pdf")

    def test_truncated_pdf(self, letter_pdf):
        # pdfium repairs many damaged files; either it parses or it raises our error type
        try:
            d = parse(letter_pdf[: len(letter_pdf) // 2], ocr="never")
        except PdfOpenError:
            return
        assert d.pages

    def test_garbage_before_header(self, letter_pdf):
        d = parse(b"X-Mailer: junk\r\n\r\n" + letter_pdf, ocr="never")
        assert d.doc_type is DocType.LETTER

    @pytest.mark.skipif(not HAS_QPDF, reason="qpdf not installed")
    def test_encrypted_pdf(self, tmp_path, letter_pdf):
        src = tmp_path / "plain.pdf"
        enc = tmp_path / "enc.pdf"
        src.write_bytes(letter_pdf)
        subprocess.run(["qpdf", "--encrypt", "geheim", "geheim", "256", "--", str(src), str(enc)], check=True)
        with pytest.raises(PdfOpenError, match="password"):
            parse(enc, ocr="never")
        d = parse(enc, ocr="never", password="geheim")
        assert d.doc_type is DocType.LETTER

    def test_blank_page_is_empty_not_ocr(self):
        d = parse(make_pdf([[]]), ocr="auto")
        assert d.pages[0].source is PageSource.EMPTY
        assert render(d, "txt") == ""
        assert d.doc_type is DocType.GENERIC

    def test_rotated_page(self):
        pdf = make_pdf(
            [paragraph(70, 100, ["Sehr geehrte Damen und Herren,", "dies ist ein Test mit gedrehter Seite."])],
            rotate=90,
        )
        d = parse(pdf, ocr="never")
        # /Rotate 90 shows the text sideways; the page frame is turned back upright
        assert d.pages[0].rotation == 90
        assert d.pages[0].stats["orientation_corrected"] == 90
        assert d.pages[0].width < d.pages[0].height
        assert "dies ist ein Test mit gedrehter Seite." in render(d, "txt")

    def test_sideways_text_is_normalised(self):
        # whole page content drawn rotated by 90° on an upright page
        items = [T(100 + i * 16, 700, f"Zeile {i} mit seitlich gedrehtem Text", 11, angle=90) for i in range(5)]
        d = parse(make_pdf([items]), ocr="never")
        assert d.pages[0].stats.get("orientation_corrected") in (90, 270)
        txt = render(d, "txt")
        assert "Zeile 0 mit seitlich gedrehtem Text" in txt

    def test_rotated_margin_note_goes_to_extras(self):
        items = paragraph(70, 100, ["Haupttext der Seite in normaler Ausrichtung.", "Noch eine Zeile Haupttext."])
        items.append(T(30, 600, "Randvermerk", 8, angle=90))
        d = parse(make_pdf([items]), ocr="never")
        assert "Randvermerk" not in render(d, "txt")
        assert "Randvermerk" in render(d, "raw")
        assert any(b.kind is BlockKind.MARGINAL for b in d.pages[0].extras)

    def test_invisible_text_layer_is_used(self):
        items = [
            T(70, 100 + i * 14, f"Unsichtbare OCR-Zeile Nummer {i} mit Inhalt", 11, invisible=True) for i in range(4)
        ]
        d = parse(make_pdf([items]), ocr="auto")
        assert d.pages[0].source is PageSource.TEXT
        assert "Unsichtbare OCR-Zeile Nummer 3" in render(d, "txt")

    def test_page_range(self, bill_pdf):
        d = parse(bill_pdf, ocr="never", first_page=2, last_page=2)
        assert [p.number for p in d.pages] == [2]

    def test_ocr_unavailable_is_reported_not_fatal(self, monkeypatch):
        from pdfgen import make_scanned_pdf

        pdf = make_scanned_pdf([[T(70, 100, "Text im Bild", 14)]], dpi=100)
        d = parse(pdf, ocr="auto", tesseract_cmd="definitely-not-tesseract-xyz")
        assert any(i.step == "ocr" for i in d.issues)
        assert d.pages[0].source is PageSource.EMPTY

    def test_timings_and_stats(self, parsed):
        d = parsed["bill"]
        assert d.timings["total"] > 0 and "layout" in d.timings
        assert d.stats["pages"] == 2


class TestPipelineCustomisation:
    def test_insert_custom_step(self, letter_pdf):
        @step("count_words")
        def count_words(ctx):
            ctx.doc.fields["word_count"] = len(ctx.doc.body_text().split())

        pipe = Pipeline().insert_after("summary", count_words)
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert d.fields["word_count"] > 50

    def test_doc_type_restricted_step_is_dispatched_only_for_type(self, letter_pdf, bill_pdf):
        calls = []
        s = FuncStep(
            "only_bills", lambda ctx: calls.append(ctx.doc.doc_type), doc_types=frozenset({DocType.PARLIAMENTARY_PRINT})
        )
        pipe = Pipeline().append(s)
        pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        pipe.run(bill_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert calls == [DocType.PARLIAMENTARY_PRINT]

    def test_failing_step_recorded(self, letter_pdf):
        def boom(ctx):
            raise RuntimeError("kaputt")

        pipe = Pipeline().insert_after("classify", FuncStep("boom", boom))
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert any(i.step == "boom" and "kaputt" in i.message for i in d.issues)
        assert d.fields["letter"]["salutation"]  # later steps still ran

    def test_failing_step_strict(self, letter_pdf):
        pipe = Pipeline().insert_after("classify", FuncStep("boom", lambda ctx: 1 / 0))
        with pytest.raises(StepError) as ei:
            pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER, strict=True))
        assert ei.value.step == "boom"

    def test_replace_and_remove(self, letter_pdf):
        pipe = (
            Pipeline()
            .remove("entities")
            .replace("letter", FuncStep("letter", lambda ctx: ctx.doc.fields.update(letter="custom")))
        )
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert d.entities == {} and d.fields["letter"] == "custom"
        with pytest.raises(KeyError):
            pipe.remove("does-not-exist")


def test_structured_lines_are_not_glued_by_flow_merge(parsed):
    txt = render(parsed["judgment"], "txt")
    assert "- Kläger - gegen" not in txt
    assert "- Kläger -" in txt
