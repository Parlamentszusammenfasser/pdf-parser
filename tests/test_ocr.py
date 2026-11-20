"""OCR path (requires tesseract with German language data)."""

import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from pazufa_pdf_parser import Ocr, OcrMode, PageSource, ParseOptions, parse, render
from pazufa_pdf_parser._pipeline.extract import _lone_numbers_missed, ocr
from pazufa_pdf_parser._pipeline.extract.ocr import parse_tsv
from pazufa_pdf_parser._pipeline.model import BBox, Word
from pazufa_pdf_parser._pipeline.pipeline import Pipeline
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
    return parse(make_scanned_pdf([LETTER_LINES]))


def test_scan_is_ocred(scanned_letter):
    d = scanned_letter
    assert d.pages[0].source is PageSource.OCR
    assert d.report.pages[0].ocr_confidence > 70
    txt = render(d, "txt")
    for phrase in (
        "Bayerische Staatskanzlei",
        "80539 München",
        "Sehr geehrte Frau Gernbauer,",
        "Änderungen",
        "Mit freundlichen Grüßen",
    ):
        assert phrase in txt, phrase


def test_rotated_scan_is_corrected():
    d = Pipeline().run(make_scanned_pdf([LETTER_LINES], rotate_image=90))
    assert d.pages[0].stats.get("orientation_corrected") in (90, 270)
    assert "Sehr geehrte Frau Gernbauer," in d.body_text()


def test_ocr_always_overrides_text_layer(letter_pdf):
    d = parse(letter_pdf, ParseOptions(ocr=OcrMode.ALWAYS, ocr_engine=Ocr(dpi=200), first_page=1, last_page=1))
    assert d.pages[0].source is PageSource.OCR
    assert "Sehr geehrte Frau Muster" in render(d, "txt")


def test_noise_is_not_in_txt_but_in_raw():
    d = parse(make_scanned_pdf([LETTER_LINES], noise=True))
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


def _word(text, x0, x1=None):
    return Word(text, BBox(x0, 755, x1 or x0 + 6, 770))


@pytest.mark.parametrize(
    "text_layer,ocr_words,kept",
    [
        ([_word("2", 85)], [_word("Seite", 466, 481)], ["2"]),
        ([_word("2", 85)], [_word("2", 84)], []),
        ([_word("Ausgegeben:", 85, 150), _word("1", 500)], [], []),
        ([_word("S", 85)], [], []),
        ([], [], []),
    ],
    ids=["lone-number", "ocr-read-it", "shares-its-row", "letter", "empty"],
)
def test_text_layer_numbers_ocr_missed(text_layer, ocr_words, kept):
    # BW annexes: tesseract drops the lone bold page number the clean text layer has
    assert [w.text for w in _lone_numbers_missed(text_layer, ocr_words)] == kept


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


# counts the OCR runs alive when one starts; `--list-langs` probes are not OCR runs
COUNTING_TESSERACT = """#!{python}
import os, subprocess, sys, time
from pathlib import Path

if "--list-langs" in sys.argv:
    sys.exit(subprocess.call(["tesseract", *sys.argv[1:]]))
running = Path({dir!r}) / "running"
running.mkdir(exist_ok=True)
me = running / str(os.getpid())
me.touch()
try:
    with open(Path({dir!r}) / "counts", "a") as f:
        f.write(f"{{len(list(running.iterdir()))}}\\n")
    time.sleep(0.2)  # long enough for runs of other parses to overlap, if the cap lets them
    sys.exit(subprocess.call(["tesseract", *sys.argv[1:]]))
finally:
    me.unlink()
"""


def test_shared_ocr_caps_tesseract_runs_across_parses(tmp_path):
    wrapper = tmp_path / "tesseract"
    wrapper.write_text(COUNTING_TESSERACT.format(python=sys.executable, dir=str(tmp_path)))
    wrapper.chmod(0o755)
    engine = Ocr(max_parallel=2, dpi=100, detect_orientation=False, tesseract_cmd=str(wrapper))
    scan = make_scanned_pdf([LETTER_LINES] * 4, dpi=100)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda _: parse(scan, ParseOptions(ocr_engine=engine)), range(3)))
    counts = [int(n) for n in (tmp_path / "counts").read_text().split()]
    assert len(counts) == 12  # one run per page, 3 x 4 pages
    assert max(counts) == 2
