"""OCR path (requires tesseract with German language data)."""

import pytest
from PIL import Image

from pazufa_pdf_parser import DocType, PageSource, parse, render
from pazufa_pdf_parser.extract import ocr
from pazufa_pdf_parser.extract.ocr import parse_tsv
from pdfgen import T, make_scanned_pdf, paragraph

pytestmark = pytest.mark.ocr

LETTER_LINES = [
    T(70, 150, "Bayerische Staatskanzlei", 12),
    T(70, 168, "Franz-Josef-Strauß-Ring 1", 12),
    T(70, 186, "80539 München", 12),
    T(400, 230, "16.07.2024", 12),
    T(70, 280, "Sehr geehrte Frau Gernbauer,", 12),
    *paragraph(
        70,
        310,
        [
            "vielen Dank für die Möglichkeit, zum Entwurf eines Gesetzes",
            "Stellung nehmen zu können. Wir begrüßen die Änderungen.",
        ],
        12,
        1.5,
    ),
    T(70, 380, "Mit freundlichen Grüßen", 12),
    T(70, 420, "Dr. Erika Musterfrau", 12),
]


@pytest.fixture(scope="module")
def scanned_letter():
    return parse(make_scanned_pdf([LETTER_LINES]), languages=("deu",))


def test_scan_is_ocred(scanned_letter):
    d = scanned_letter
    assert d.pages[0].source is PageSource.OCR
    assert d.pages[0].stats["ocr_mean_confidence"] > 70
    txt = render(d, "txt")
    for phrase in (
        "Bayerische Staatskanzlei",
        "80539 München",
        "Sehr geehrte Frau Gernbauer,",
        "Änderungen",
        "Mit freundlichen Grüßen",
    ):
        assert phrase in txt, phrase


def test_scan_fields(scanned_letter):
    d = scanned_letter
    assert d.doc_type is DocType.LETTER
    f = d.fields["letter"]
    assert f["recipient"]["postal_code"] == "80539"
    assert f["date"] == "2024-07-16"
    assert f["signatory"]["name"] == "Dr. Erika Musterfrau"


def test_rotated_scan_is_corrected():
    d = parse(make_scanned_pdf([LETTER_LINES], rotate_image=90), languages=("deu",))
    assert d.pages[0].stats.get("orientation_corrected") in (90, 270)
    assert "Sehr geehrte Frau Gernbauer," in render(d, "txt")


def test_ocr_always_overrides_text_layer(letter_pdf):
    d = parse(letter_pdf, ocr="always", dpi=200, first_page=1, last_page=1)
    assert d.pages[0].source is PageSource.OCR
    assert "Sehr geehrte Frau Muster" in render(d, "txt")


def test_noise_is_not_in_txt_but_in_raw():
    d = parse(make_scanned_pdf([LETTER_LINES], noise=True), languages=("deu",))
    txt = render(d, "txt")
    assert "Sehr geehrte Frau Gernbauer," in txt
    assert len(render(d, "raw")) >= len(txt) - 5


def test_parse_tsv_scaling():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t2480\t3508\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t300\t600\t200\t40\t95.5\tHallo\n"
        "5\t1\t1\t1\t1\t2\t520\t600\t180\t40\t91.0\tWelt\n"
        "5\t1\t1\t1\t1\t3\t720\t600\t10\t40\t-1\t\n"
    )
    words = parse_tsv(tsv, 72 / 300)
    assert [w.text for w in words] == ["Hallo", "Welt"]
    assert words[0].bbox.x0 == pytest.approx(72.0)
    assert words[0].confidence == 95.5
    assert words[0].size > 9


@pytest.mark.parametrize(
    "user_limit,expected",
    [(None, "1"), ("3", "3")],
    ids=["default-single-thread", "explicit-setting-wins"],
)
def test_tesseract_runs_single_threaded(monkeypatch, user_limit, expected):
    if user_limit is None:
        monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    else:
        monkeypatch.setenv("OMP_THREAD_LIMIT", user_limit)
    envs = []

    def fake_run(args, **kw):
        envs.append(kw["env"])
        return ocr.subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    img = Image.new("L", (10, 10), 255)
    ocr.detect_rotation(img, 300)
    ocr.run_tesseract_tsv(img, "deu", 300)
    assert [e["OMP_THREAD_LIMIT"] for e in envs] == [expected, expected]
