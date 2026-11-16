"""End-to-end behaviour on synthetic PDFs (text layer)."""

import io
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import HAS_QPDF
from pazufa_pdf_parser import (
    BlockKind,
    FuncStep,
    Ocr,
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


class TestText:
    def test_letter_text_quality(self, parsed):
        txt = render(parsed["letter"], "txt")
        assert "Änderung des Testgesetzes" in txt  # de-hyphenated across lines
        assert "einigen Punkten" in txt
        assert "berücksichtigt werden könnten" in txt
        assert "- 2 -" not in txt  # page number removed
        assert "Registergericht" not in txt  # repeating footer removed
        # paragraph continued across the page break is not glued to the closing
        assert "\n\nMit freundlichen Grüßen" in txt

    def test_bill_running_footer_removed(self, parsed):
        d = parsed["bill"]
        assert "Seite 2" not in render(d, "txt")

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
        assert "Sehr geehrte Frau Muster," in render(d, "txt")

    @pytest.mark.skipif(not HAS_QPDF, reason="qpdf not installed")
    def test_encrypted_pdf(self, tmp_path, letter_pdf):
        src = tmp_path / "plain.pdf"
        enc = tmp_path / "enc.pdf"
        src.write_bytes(letter_pdf)
        subprocess.run(["qpdf", "--encrypt", "geheim", "geheim", "256", "--", str(src), str(enc)], check=True)
        with pytest.raises(PdfOpenError, match="password"):
            parse(enc, ocr="never")
        d = parse(enc, ocr="never", password="geheim")
        assert "Sehr geehrte Frau Muster," in render(d, "txt")

    def test_blank_page_is_empty_not_ocr(self):
        d = parse(make_pdf([[]]), ocr="auto")
        assert d.pages[0].source is PageSource.EMPTY
        assert render(d, "txt") == ""

    def test_rotated_page(self):
        pdf = make_pdf(
            [paragraph(70, 100, ["Sehr geehrte Damen und Herren,", "dies ist ein Test mit gedrehter Seite."])],
            rotate=90,
        )
        d = Pipeline().run(pdf, ParseOptions(ocr=OcrMode.NEVER))
        # /Rotate 90 shows the text sideways; the page frame is turned back upright
        assert d.pages[0].rotation == 90
        assert d.pages[0].stats["orientation_corrected"] == 90
        assert d.pages[0].width < d.pages[0].height
        assert "dies ist ein Test mit gedrehter Seite." in d.body_text()

    def test_sideways_text_is_normalised(self):
        # whole page content drawn rotated by 90° on an upright page
        items = [T(100 + i * 16, 700, f"Zeile {i} mit seitlich gedrehtem Text", 11, angle=90) for i in range(5)]
        d = Pipeline().run(make_pdf([items]), ParseOptions(ocr=OcrMode.NEVER))
        assert d.pages[0].stats.get("orientation_corrected") in (90, 270)
        assert "Zeile 0 mit seitlich gedrehtem Text" in d.body_text()

    def test_rotated_margin_note_goes_to_extras(self):
        items = paragraph(70, 100, ["Haupttext der Seite in normaler Ausrichtung.", "Noch eine Zeile Haupttext."])
        items.append(T(30, 600, "Randvermerk", 8, angle=90))
        d = parse(make_pdf([items]), ocr="never")
        assert "Randvermerk" not in render(d, "txt")
        assert "Randvermerk" in render(d, "raw")
        assert any(b.kind is BlockKind.MARGINAL for b in d.blocks)

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
        d = parse(pdf, ocr="auto", ocr_engine=Ocr(tesseract_cmd="definitely-not-tesseract-xyz"))
        assert any(i.step == "ocr" for i in d.report.issues)
        assert d.pages[0].source is PageSource.EMPTY

    def test_text_pages_do_not_wait_for_ocr(self, letter_pdf):
        engine = Ocr(max_parallel=1)
        with ThreadPoolExecutor(1) as ex, engine._slots:  # the only OCR slot is taken
            d = ex.submit(parse, letter_pdf, ocr_engine=engine).result(timeout=30)
        assert {p.source for p in d.pages} == {PageSource.TEXT}

    def test_ocr_engine_settings(self):
        assert ParseOptions().ocr_engine is ParseOptions().ocr_engine  # parses share one limit by default
        with pytest.raises(ValueError, match="max_parallel"):
            Ocr(max_parallel=0)

    def test_timings_and_stats(self, bill_pdf):
        d = Pipeline().run(bill_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert d.timings["total"] > 0 and "layout" in d.timings
        assert "flow_joins" in d.stats


class TestPipelineCustomisation:
    def test_insert_custom_step(self, letter_pdf):
        @step("count_words")
        def count_words(ctx):
            ctx.doc.stats["word_count"] = len(ctx.doc.body_text().split())

        pipe = Pipeline().insert_after("flow", count_words)
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert d.stats["word_count"] > 50

    def test_failing_step_recorded(self, letter_pdf):
        def boom(ctx):
            raise RuntimeError("kaputt")

        pipe = Pipeline().insert_after("furniture", FuncStep("boom", boom))
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert any(i.step == "boom" and "kaputt" in i.message for i in d.issues)
        assert "flow_joins" in d.stats  # later steps still ran

    def test_failing_step_strict(self, letter_pdf):
        pipe = Pipeline().insert_after("furniture", FuncStep("boom", lambda ctx: 1 / 0))
        with pytest.raises(StepError) as ei:
            pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER, strict=True))
        assert ei.value.step == "boom"

    def test_replace_and_remove(self, letter_pdf):
        pipe = (
            Pipeline()
            .remove("flow")
            .replace("furniture", FuncStep("furniture", lambda ctx: ctx.doc.stats.update(furniture="custom")))
        )
        d = pipe.run(letter_pdf, ParseOptions(ocr=OcrMode.NEVER))
        assert "flow_joins" not in d.stats and d.stats["furniture"] == "custom"
        with pytest.raises(KeyError):
            pipe.remove("does-not-exist")


def test_structured_lines_are_not_glued_by_flow_merge(parsed):
    txt = render(parsed["judgment"], "txt")
    assert "- Kläger - gegen" not in txt
    assert "- Kläger -" in txt
