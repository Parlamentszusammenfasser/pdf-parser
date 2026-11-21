"""End-to-end behaviour on synthetic PDFs (text layer)."""

import copy
import hashlib
import io
import pickle
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from conftest import HAS_QPDF, NO_OCR
from pazufa_pdf_parser import (
    BlockKind,
    Ocr,
    OcrMode,
    OcrUnavailableError,
    PageSource,
    ParseOptions,
    PdfOpenError,
    Severity,
    StepError,
    parse,
    render,
)
from pazufa_pdf_parser._pipeline.pipeline import FuncStep, Pipeline, step
from pdfgen import T, make_pdf, make_scanned_pdf, paragraph


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
        a = parse(p, NO_OCR)
        b = parse(str(p), NO_OCR)
        c = parse(io.BytesIO(letter_pdf), NO_OCR)
        assert a.sha256 == b.sha256 == c.sha256
        assert render(a, "txt") == render(c, "txt")

    @pytest.mark.parametrize(
        "data,error",
        [(b"hello world", "not a PDF"), (b"", "empty"), (make_pdf([]), "no readable pages")],
        ids=["not-a-pdf", "empty", "no-pages"],
    )
    def test_unreadable_input(self, data, error):
        with pytest.raises(PdfOpenError, match=error):
            parse(data)

    def test_missing_file(self, tmp_path):
        with pytest.raises(PdfOpenError):
            parse(tmp_path / "nope.pdf")

    def test_truncated_pdf(self, letter_pdf):
        # pdfium repairs many damaged files; either it parses or it raises our error type
        try:
            d = parse(letter_pdf[: len(letter_pdf) // 2], NO_OCR)
        except PdfOpenError:
            return
        assert d.pages

    def test_garbage_before_header(self, letter_pdf):
        data = b"X-Mailer: junk\r\n\r\n" + letter_pdf
        d = parse(data, NO_OCR)
        assert "Sehr geehrte Frau Muster," in render(d, "txt")
        assert d.sha256 == hashlib.sha256(data).hexdigest()  # callers dedupe by the hash of the file they hold

    @pytest.mark.skipif(not HAS_QPDF, reason="qpdf not installed")
    def test_encrypted_pdf(self, tmp_path, letter_pdf):
        src = tmp_path / "plain.pdf"
        enc = tmp_path / "enc.pdf"
        src.write_bytes(letter_pdf)
        subprocess.run(["qpdf", "--encrypt", "geheim", "geheim", "256", "--", str(src), str(enc)], check=True)
        with pytest.raises(PdfOpenError, match="password"):
            parse(enc, NO_OCR)
        d = parse(enc, replace(NO_OCR, password="geheim"))
        assert "Sehr geehrte Frau Muster," in render(d, "txt")

    def test_blank_page_is_empty_not_ocr(self):
        d = parse(make_pdf([[]]))
        assert d.pages[0].source is PageSource.EMPTY
        assert render(d, "txt") == ""

    @pytest.mark.parametrize(
        "mapped,text",
        [("\U0001f600", "Emoji \U0001f600 im Satz"), ("\ud83d", "Emoji \ufffd im Satz")],
        ids=["emoji", "lone-surrogate"],
    )
    def test_characters_beyond_utf16_units(self, mapped, text):
        # pdfium reports UTF-16 units: an emoji arrives as two surrogates, which no output could encode
        line = "Ein Satz mit Emoji A im Satz und weiterem Text dahinter"
        d = parse(make_pdf([[T(70, 100, line)]], to_unicode={"A": mapped}), NO_OCR)
        assert text in d.text()
        for fmt in ("raw", "txt", "html", "json"):
            render(d, fmt).encode("utf-8")

    @pytest.mark.parametrize("rotate", [0, 90], ids=["upright", "rotated"])
    def test_text_outside_the_crop_box_is_dropped(self, rotate):
        items = [T(70, 100, "Sichtbarer Text oben"), T(70, 600, "Weggeschnittener Text unten")]
        d = parse(make_pdf([items], crop_box=(0, 421, 595, 842), rotate=rotate), NO_OCR)
        assert d.text() == "Sichtbarer Text oben"

    def test_rotated_page(self):
        pdf = make_pdf(
            [paragraph(70, 100, ["Sehr geehrte Damen und Herren,", "dies ist ein Test mit gedrehter Seite."])],
            rotate=90,
        )
        d = Pipeline().run(pdf, NO_OCR)
        # /Rotate 90 shows the text sideways; the page frame is turned back upright
        assert d.pages[0].rotation == 90
        assert d.pages[0].stats["orientation_corrected"] == 90
        assert d.pages[0].width < d.pages[0].height
        assert "dies ist ein Test mit gedrehter Seite." in d.body_text()

    def test_sideways_text_is_normalised(self):
        # whole page content drawn rotated by 90° on an upright page
        items = [T(100 + i * 16, 700, f"Zeile {i} mit seitlich gedrehtem Text", 11, angle=90) for i in range(5)]
        d = Pipeline().run(make_pdf([items]), NO_OCR)
        assert d.pages[0].stats.get("orientation_corrected") in (90, 270)
        assert "Zeile 0 mit seitlich gedrehtem Text" in d.body_text()

    def test_rotated_margin_note_goes_to_extras(self):
        items = paragraph(70, 100, ["Haupttext der Seite in normaler Ausrichtung.", "Noch eine Zeile Haupttext."])
        items.append(T(30, 600, "Randvermerk", 8, angle=90))
        d = parse(make_pdf([items]), NO_OCR)
        assert "Randvermerk" not in render(d, "txt")
        assert "Randvermerk" in render(d, "raw")
        assert any(b.kind is BlockKind.MARGINAL for b in d.blocks)

    def test_invisible_text_layer_is_used(self):
        items = [
            T(70, 100 + i * 14, f"Unsichtbare OCR-Zeile Nummer {i} mit Inhalt", 11, invisible=True) for i in range(4)
        ]
        d = parse(make_pdf([items]))
        assert d.pages[0].source is PageSource.TEXT
        assert "Unsichtbare OCR-Zeile Nummer 3" in render(d, "txt")

    def test_page_range(self, bill_pdf):
        d = parse(bill_pdf, replace(NO_OCR, first_page=2, last_page=2))
        assert [p.number for p in d.pages] == [2] and d.report.issues == ()

    def test_ocr_unavailable_is_reported_not_fatal(self, monkeypatch):
        from pdfgen import make_scanned_pdf

        pdf = make_scanned_pdf([[T(70, 100, "Text im Bild", 14)]], dpi=100)
        options = ParseOptions(ocr_engine=Ocr(tesseract_cmd="definitely-not-tesseract-xyz"))
        d = parse(pdf, options)
        assert [(i.step, i.code) for i in d.report.issues] == [("ocr", "ocr_unavailable")]
        assert d.pages[0].source is PageSource.EMPTY and d.pages[0].needs_ocr
        assert d.pages[0].ocr_reason.endswith("; not OCRed: tesseract unavailable")
        with pytest.raises(OcrUnavailableError):  # strict: the cause itself, not a StepError around it
            parse(pdf, replace(options, strict=True))

    def test_text_pages_do_not_wait_for_ocr(self, letter_pdf):
        engine = Ocr(max_parallel=1)
        with ThreadPoolExecutor(1) as ex, engine._slots:  # the only OCR slot is taken
            d = ex.submit(parse, letter_pdf, ParseOptions(ocr_engine=engine)).result(timeout=30)
        assert {p.source for p in d.pages} == {PageSource.TEXT}

    def test_ocr_slots_are_first_come_first_served(self, tmp_path):
        # a one-page scan queued during a long scan's first page must not wait for all of its pages
        log = tmp_path / "runs"
        engine = Ocr(max_parallel=1, dpi=72, detect_orientation=False, tesseract_cmd=fake_tesseract(tmp_path, log))
        options = ParseOptions(ocr_engine=engine)
        finished = []

        def run(name, pages):
            parse(make_scanned_pdf([[T(70, 100, name, 14)]] * pages, dpi=72), options)
            finished.append(name)

        long_scan = threading.Thread(target=run, args=("lang", 5))
        long_scan.start()
        while not log.exists():
            time.sleep(0.01)
        run("kurz", 1)
        long_scan.join()
        assert finished == ["kurz", "lang"]

    def test_ocr_failure(self, tmp_path):
        log = tmp_path / "runs"
        engine = Ocr(max_parallel=1, dpi=72, detect_orientation=False, tesseract_cmd=fake_tesseract(tmp_path, log, 1))
        d = parse(make_scanned_pdf([[T(70, 100, "Seite", 14)]], dpi=72), ParseOptions(ocr_engine=engine))
        assert [(i.severity, i.code, i.page) for i in d.report.issues] == [(Severity.ERROR, "ocr_failed", 1)]
        assert d.pages[0].source is PageSource.EMPTY and d.pages[0].needs_ocr
        assert d.pages[0].ocr_reason.endswith("; not OCRed: OCR failed")
        # strict: Executor.map drops the queued pages once the loop raises; they must not keep the slots busy
        log.unlink()
        with pytest.raises(StepError):
            parse(
                make_scanned_pdf([[T(70, 100, "Seite", 14)]] * 6, dpi=72), ParseOptions(ocr_engine=engine, strict=True)
            )
        assert len(log.read_text().split()) < 6

    @pytest.mark.parametrize(
        ("pages", "limit", "mode", "runs", "severity"),
        [
            (3, 2, OcrMode.AUTO, 0, Severity.WARNING),
            (0, 0, OcrMode.ALWAYS, 0, Severity.ERROR),
            (3, 3, OcrMode.AUTO, 3, None),
            (0, 0, OcrMode.AUTO, 0, None),
        ],
        ids=["over-limit-skips-ocr", "forced-ocr-over-limit-is-error", "at-limit-ocrs", "text-pages-do-not-count"],
    )
    def test_max_ocr_pages(self, tmp_path, letter_pdf, pages, limit, mode, runs, severity):
        # pages=0 means the born-digital letter instead of a scan
        log = tmp_path / "runs"
        engine = Ocr(dpi=72, detect_orientation=False, tesseract_cmd=fake_tesseract(tmp_path, log))
        pdf = make_scanned_pdf([[T(70, 100, "Seite", 14)]] * pages, dpi=72) if pages else letter_pdf
        d = parse(pdf, ParseOptions(ocr=mode, ocr_engine=engine, max_ocr_pages=limit))
        assert (len(log.read_text().split()) if log.exists() else 0) == runs
        assert [i.severity for i in d.report.issues if "over the limit" in i.message] == (
            [severity] if severity else []
        )
        if severity:
            assert {p.source for p in d.pages} == {PageSource.EMPTY if pages else PageSource.TEXT}
        assert all(("not OCRed: " in r.ocr_reason) == bool(severity) for r in d.pages)
        # the letter's text layer is fine even when OCR was forced and skipped
        assert all(p.needs_ocr == bool(severity and pages) for p in d.pages)
        if severity is Severity.ERROR:  # strict raises at the first ERROR issue, not only at failing steps
            with pytest.raises(StepError, match="over the limit") as e:
                parse(pdf, ParseOptions(ocr=mode, ocr_engine=engine, max_ocr_pages=limit, strict=True))
            assert e.value.step == "ocr" and e.value.issue.code == "ocr_limit"

    def test_ocr_engine_settings(self):
        opts = ParseOptions()
        assert opts.ocr_engine is ParseOptions().ocr_engine  # parses share one limit by default
        assert copy.deepcopy(opts).ocr_engine is opts.ocr_engine is copy.copy(opts.ocr_engine)  # copies share it
        engine = Ocr(
            languages=("eng",), dpi=150, max_parallel=1, timeout=5.0, tesseract_cmd="t", detect_orientation=False
        )
        clone = pickle.loads(pickle.dumps(engine))  # noqa: S301 - e.g. sent to a process pool
        assert repr(clone) == repr(engine) and clone._slots is not engine._slots  # every setting, own limit
        assert Ocr(languages="deu+eng").languages == ("deu", "eng")  # as on the tesseract command line
        # was compared by identity and silently ran as "auto"
        assert ParseOptions(ocr="never").ocr is OcrMode.NEVER  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "make,error",
        [
            (lambda: ParseOptions(ocr="sometimes"), "sometimes"),
            (lambda: Ocr(max_parallel=0), "max_parallel"),
            (lambda: Ocr(max_parallel=1.5), "max_parallel"),  # a fractional slot count never blocks
            (lambda: Ocr(dpi=0), "dpi"),
            (lambda: Ocr(dpi=None), "dpi"),  # None means "no limit" only for the page options
            (lambda: Ocr(timeout=0), "timeout"),
            (lambda: Ocr(timeout=None), "timeout"),
            (lambda: ParseOptions(max_ocr_pages=-1), "max_ocr_pages"),  # would turn OCR off for every scan
            (lambda: ParseOptions(max_ocr_pages=True), "max_ocr_pages"),
            (lambda: ParseOptions(first_page=0), "first_page"),  # read as "all pages"
            (lambda: ParseOptions(last_page=1.5), "last_page"),
            (lambda: ParseOptions(first_page=3, last_page=2), "after last_page"),  # read as no pages
        ],
        ids=[
            "ocr-mode",
            "no-slots",
            "fractional-slots",
            "dpi",
            "no-dpi",
            "timeout",
            "no-timeout",
            "negative-ocr-limit",
            "bool-ocr-limit",
            "page-zero",
            "fractional-page",
            "reversed-range",
        ],
    )
    def test_invalid_options(self, make, error):
        with pytest.raises(ValueError, match=error):
            make()

    def test_range_past_the_last_page(self, bill_pdf):
        d = parse(bill_pdf, replace(NO_OCR, first_page=5))
        assert d.pages == () and [i.message for i in d.report.issues] == ["first_page 5 is beyond the last page, 2"]

    def test_timings_and_stats(self, bill_pdf):
        d = Pipeline().run(bill_pdf, NO_OCR)
        assert d.timings["total"] > 0 and "layout" in d.timings
        assert "flow_joins" in d.stats


class TestPipelineCustomisation:
    def test_insert_custom_step(self, letter_pdf):
        @step("count_words")
        def count_words(ctx):
            ctx.doc.stats["word_count"] = len(ctx.doc.body_text().split())

        pipe = Pipeline().insert_after("flow", count_words)
        d = pipe.run(letter_pdf, NO_OCR)
        assert d.stats["word_count"] > 50

    def test_failing_step_recorded(self, letter_pdf):
        def boom(ctx):
            raise RuntimeError("kaputt")

        pipe = Pipeline().insert_after("furniture", FuncStep("boom", boom))
        d = pipe.run(letter_pdf, NO_OCR)
        assert any(i.step == "boom" and "kaputt" in i.message for i in d.issues)
        assert "flow_joins" in d.stats  # later steps still ran

    def test_failing_step_strict(self, letter_pdf):
        pipe = Pipeline().insert_after("furniture", FuncStep("boom", lambda ctx: 1 / 0))
        with pytest.raises(StepError) as ei:
            pipe.run(letter_pdf, replace(NO_OCR, strict=True))
        assert ei.value.step == "boom"

    def test_replace_and_remove(self, letter_pdf):
        pipe = (
            Pipeline()
            .remove("flow")
            .replace("furniture", FuncStep("furniture", lambda ctx: ctx.doc.stats.update(furniture="custom")))
        )
        d = pipe.run(letter_pdf, NO_OCR)
        assert "flow_joins" not in d.stats and d.stats["furniture"] == "custom"
        with pytest.raises(KeyError):
            pipe.remove("does-not-exist")


def test_structured_lines_are_not_glued_by_flow_merge(parsed):
    txt = render(parsed["judgment"], "txt")
    assert "- Kläger - gegen" not in txt
    assert "- Kläger -" in txt


def fake_tesseract(tmp_path, log, exit_code=0):
    """A tesseract stand-in that takes 0.3 s per page, finds no words and logs each run to ``log``."""
    script = tmp_path / "tesseract"
    script.write_text(
        f"""#!{sys.executable}
import sys, time
if "--list-langs" in sys.argv:
    print("List of available languages (1):\\ndeu")
    sys.exit(0)
with open({str(log)!r}, "a") as f:
    f.write("run\\n")
sys.stdin.buffer.read()
time.sleep(0.3)
print("level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext")
sys.exit({exit_code})
"""
    )
    script.chmod(0o755)
    return str(script)
