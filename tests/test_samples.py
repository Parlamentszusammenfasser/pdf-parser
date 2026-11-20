"""Regression tests against real-world sample PDFs.

``tests/samples/by`` holds one Bavarian PDF per layout case, ``tests/samples/bw`` the
Baden-Württemberg PDFs that broke scraper-bw, ``tests/samples/sh`` a Schleswig-Holstein
synopsis (see their READMEs).
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pazufa_pdf_parser import BlockKind, OcrMode, ParseOptions, PdfDocument, parse, render
from pazufa_pdf_parser._pipeline.pipeline import Pipeline

pytestmark = pytest.mark.samples

BY_DIR = Path(__file__).parent / "samples" / "by"
# these have pages the parser OCRs; without tesseract their text is missing or incomplete
BY_OCR = {
    "drs-staatsvertrag-bilingual-rotated-maps.pdf",
    "letter-image-letterhead-ocr-merge.pdf",
    "scan-garbled-font.pdf",
    "scan-letter-continuation-page.pdf",
    "scan-letter.pdf",
    "scan-reading-order.pdf",
    "scan-rotate-270-footer-logo.pdf",
    "scan-rotate-270.pdf",
    "scan-rotate-90.pdf",
    "scan-statement-sidebar.pdf",
    "statement-ti-ligature-mixed-scan.pdf",
}
BW_DIR = Path(__file__).parent / "samples" / "bw"
BW_OCR = {"drs-17-1104-garbled-146p.pdf", "drs-17-1201-ascii-shift.pdf", "drs-17-6014-garbled-annex.pdf"}
BW_SLOW = {"drs-17-1104-garbled-146p.pdf"}  # 131 OCR pages, ~30 s
SH_DIR = Path(__file__).parent / "samples" / "sh"


def _params(directory, ocr, slow=frozenset()):
    return [
        pytest.param(
            p.name,
            marks=[m for m, on in ((pytest.mark.ocr, p.name in ocr), (pytest.mark.slow, p.name in slow)) if on],
            id=p.stem,
        )
        for p in sorted(directory.glob("*.pdf"))
    ]


BY_SAMPLES = _params(BY_DIR, BY_OCR)
BW_SAMPLES = _params(BW_DIR, BW_OCR, BW_SLOW)
SH_SAMPLES = _params(SH_DIR, set())

_cache: dict[str, object] = {}


def _path(name):
    return next(d / name for d in (BY_DIR, BW_DIR, SH_DIR) if (d / name).exists())


def sample(name):
    if name not in _cache:
        _cache[name] = parse(_path(name))
    return _cache[name]


@pytest.mark.parametrize("name", [*BY_SAMPLES, *BW_SAMPLES, *SH_SAMPLES])
def test_renders_and_round_trips(name):
    d = sample(name)
    assert not [i for i in d.report.issues if i.severity == "error"]
    for fmt in ("raw", "txt", "html", "json"):
        assert render(d, fmt).strip()
    assert PdfDocument.from_json(d.to_json()) == d


def test_clean_drucksache():
    # best case: a born-digital BY Drucksache whose text must come out exactly clean
    txt = render(sample("drs-clean.pdf"), "txt")
    assert "Drucksache 19/9342" not in txt  # masthead of p. 1 and running header of pp. 2-3 removed
    assert "Seite" not in txt
    assert "Drucksachen, Plenarprotokolle" not in txt  # page-1 footer removed
    assert txt.rstrip().endswith("I. Vizepräsident")
    assert "Dieses Gesetz tritt am 1. Januar 2026 in Kraft." in txt
    created = datetime(2025, 12, 11, 12, 48, 19, tzinfo=timezone(timedelta(hours=1)))
    assert sample("drs-clean.pdf").metadata.created == created


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


@pytest.mark.parametrize(
    "name,sources,anchors",
    [
        ("drs-17-0273-clean.pdf", {"text": 4}, ["A. Zielsetzung"]),
        pytest.param(
            "drs-17-1201-ascii-shift.pdf",
            {"text": 1, "ocr": 4},
            ["Änderungsantrag"],
            marks=pytest.mark.ocr,
        ),
        pytest.param(
            "drs-17-1104-garbled-146p.pdf",
            {"text": 15, "ocr": 131},
            ["Empfehlung und Bericht"],
            marks=[pytest.mark.ocr, pytest.mark.slow],
        ),
        pytest.param(
            "drs-17-6014-garbled-annex.pdf",
            {"text": 1, "ocr": 2},
            ["Städtetag Baden-Württemberg", "Beamtenbund"],
            marks=pytest.mark.ocr,
        ),
    ],
    ids=["clean", "ascii-shift", "garbled-146p", "garbled-annex"],
)
def test_bw_drucksache_text(name, sources, anchors):
    # BW annexes embed fonts with broken ToUnicode maps (ASCII +29 shift, Latin-Extended mojibake)
    d = sample(name)
    assert Counter(p.source.value for p in d.pages) == sources
    txt = render(d, "txt")
    assert all(a in txt for a in anchors)
    assert not _CONTROL.search(txt)
    assert not re.search(r"[\u0100-\u024f]{3}", txt)
    assert "Landtag von Baden-Württemberg Drucksache" not in txt  # running header


@pytest.mark.ocr
def test_bw_ascii_shift_pages_keep_their_number():
    # each Änderungsantrag carries its own number "17/1201-N" in the shifted font
    d = sample("drs-17-1201-ascii-shift.pdf")
    assert d.pages[0].source.value == "text"
    for p in d.pages[1:]:
        assert p.source.value == "ocr"
        assert set(re.findall(r"17/1201-\d+", d.text(pages=[p.number]))) == {f"17/1201-{p.number - 1}"}


@pytest.mark.parametrize(
    "name,issued",
    [
        ("drs-17-0273-clean.pdf", "Eingegangen: 22.6.2021 / Ausgegeben: 25.6.2021 1"),
        pytest.param("drs-17-1201-ascii-shift.pdf", "Ausgegeben: 7.1.2022", marks=pytest.mark.ocr),
        pytest.param("drs-17-6014-garbled-annex.pdf", "Ausgegeben: 4.1.2024", marks=pytest.mark.ocr),
    ],
    ids=["clean", "ascii-shift", "garbled-annex"],
)
def test_bw_drucksache_footer(name, issued):
    # scraper-bw reads the issue date from the page-1 footer, which is furniture with its two columns intact
    page = sample(name).pages[0]
    assert issued in page.furniture_text()
    assert "Der Landtag druckt auf Recyclingpapier, ausgezeichnet mit dem Umweltzeichen" in page.furniture_text()
    assert "Ausgegeben" not in page.text() and "Recyclingpapier" not in page.text()


def _numbers(first, last):
    return [str(n) for n in range(first, last + 1)]


@pytest.mark.parametrize(
    "name,printed",
    [
        ("plpr-18-10.pdf", ["II", *_numbers(259, 305)]),  # page-number lines
        ("protokollauszug-24p.pdf", _numbers(1, 23)),  # "… 19. Wahlperiode 1"
        (
            "gvbl-landscape-tables.pdf",  # "178 Bayerisches …", "… 179"; rotated pages print theirs in the margin
            [*_numbers(178, 192), None, None, None, *_numbers(196, 204)],
        ),
        ("plenum-tagesordnung.pdf", _numbers(2, 23)),  # "Bayerischer Landtag Seite 2"
        ("drs-clean.pdf", _numbers(2, 3)),  # "Drucksache 19/9342 … Seite 2"
        ("drs-17-0273-clean.pdf", _numbers(2, 4)),  # constant "Drucksache 17 / 273" is no page number
        ("drs-20-3769-synopsis.pdf", _numbers(2, 6)),
        ("gbl-2026-12.pdf", ["2"]),  # "Seite 2 von 2"
        ("to-18-14-speaking-times.pdf", _numbers(2, 3)),
        ("letter-sidebar.pdf", _numbers(2, 4)),
        ("statement-toc-dot-leaders.pdf", _numbers(2, 10)),
        ("statement-page-break.pdf", ["2"]),  # "… | Seite 2 von 2" in the header
        ("email-forwarded-with-statement.pdf", ["2", "1", "2", "3"]),  # the attached statement counts from 1
        pytest.param(
            "drs-17-1201-ascii-shift.pdf",
            _numbers(2, 5),
            marks=[pytest.mark.ocr, pytest.mark.xfail(strict=True, reason="#34: tesseract drops the lone page number")],
        ),
        pytest.param("drs-17-6014-garbled-annex.pdf", ["14", "19"], marks=pytest.mark.ocr),  # pages of an annex
    ],
    ids=[
        "page-number-line",
        "closing-header",
        "alternating-header",
        "seite",
        "seite-in-header",
        "constant-number",
        "synopsis",
        "seite-von",
        "agenda",
        "letter",
        "statement",
        "seite-von-in-header",
        "attachment",
        "ascii-shift",
        "annex",
    ],
)
def test_printed_pages(name, printed):
    # scraper-bw maps protocol agenda items to PDF pages by the printed page number; page 1 has its own test
    pages = sample(name).pages
    assert [p.printed_page for p in pages[1:]] == printed
    assert all(len([b for b in p.blocks if b.kind is BlockKind.PAGE_NUMBER]) <= 1 for p in pages)


@pytest.mark.parametrize(
    "name,printed",
    [
        ("drs-clean.pdf", None),  # mastheads carry no number
        ("protokollauszug-24p.pdf", None),  # unnumbered cover sheet
        ("plenum-tagesordnung.pdf", None),
        ("drs-20-3769-synopsis.pdf", None),
        ("gbl-2026-12.pdf", None),
        ("statement-page-break.pdf", "1"),
        ("email-forwarded-with-statement.pdf", "1"),
        pytest.param(
            "plpr-18-10.pdf",
            "I",
            marks=pytest.mark.xfail(strict=True, reason='#34: page 1\'s printed "I" is read into the footer beside it'),
        ),
        ("drs-17-0273-clean.pdf", "1"),  # closes the "Ausgegeben: …" footer row
        pytest.param(
            "letter-sidebar.pdf",
            "1",
            marks=pytest.mark.xfail(strict=True, reason='#34: "1 / 4" closes a footer line beside the address'),
        ),
        pytest.param(
            "gvbl-landscape-tables.pdf",
            "177",
            marks=pytest.mark.xfail(strict=True, reason='#34: "177" is read into the masthead heading beside it'),
        ),
    ],
    ids=[
        "masthead",
        "cover",
        "agenda",
        "synopsis",
        "gesetzblatt",
        "seite-von-in-header",
        "e-mail",
        "protocol",
        "bw-drucksache",
        "letter",
        "gvbl",
    ],
)
def test_first_printed_page(name, printed):
    assert sample(name).pages[0].printed_page == printed


def test_bw_protocol_speech_stays_in_body():
    assert "Präsident Thomas Strobl: Guten Morgen" in _txt("plpr-18-10.pdf")


@pytest.mark.parametrize(
    "name,page,line,last_page",
    [
        ("drs-17-0273-clean.pdf", 1, "Landtag von Baden-Württemberg Drucksache 17 / 273", None),
        ("drs-17-0273-clean.pdf", 1, "Landtag von Baden-Württemberg Drucksache 17 / 273", 1),  # nothing repeats it
        ("drs-clean.pdf", 1, "19. Wahlperiode 10.12.2025 Drucksache 19/9342", None),
        ("drs-clean.pdf", 2, "Drucksache 19/9342 Bayerischer Landtag 19. Wahlperiode Seite 2", None),
        (
            "plpr-18-10.pdf",
            3,
            "Landtag von Baden-Württemberg – 18. Wahlperiode – 10. Sitzung – Donnerstag, 23. Juli 2026",
            None,
        ),
        ("drs-20-3769-synopsis.pdf", 2, "Drucksache 20/3769 Schleswig-Holsteinischer Landtag – 20.Wahlperiode", None),
        ("protokollauszug-24p.pdf", 2, "41. Plenum, 04.02.2025 Bayerischer Landtag – 19. Wahlperiode 1", None),
        ("gbl-2026-12.pdf", 2, "Seite 2 von 2", None),
        ("email-forwarded-with-statement.pdf", 3, "1 von 3", None),  # above a four-line footer
    ],
    ids=[
        "bw-masthead",
        "bw-masthead-first-page-only",
        "by-masthead",
        "by-running-header",
        "protocol-header",
        "synopsis-header",
        "closing-number",
        "seite-von",
        "page-number-above-footer",
    ],
)
def test_furniture_text(name, page, line, last_page):
    # scraper-bw trusts the printed "Ausgegeben" date only below the Drucksache's own header
    d = sample(name) if last_page is None else parse(_path(name), ParseOptions(ocr=OcrMode.NEVER, last_page=last_page))
    p = d.pages[page - 1]
    assert line in p.furniture_text().splitlines()
    assert line not in p.text()


@pytest.mark.xfail(strict=True, reason="#24: ToC entries split at line ends")
def test_bw_protocol_toc_entries_joined():
    txt = _txt("plpr-18-10.pdf")
    toc = txt[: txt.index("Präsident Thomas Strobl: Guten Morgen")]
    # "Staats-" / "vertragsentwürfe" ends one paragraph and starts the next
    assert not re.search(r"[a-zäöüß]-\n\n[a-zäöüß]", toc)


@pytest.mark.xfail(strict=True, reason="#8: speaking-time column read before the agenda items")
def test_bw_agenda_order():
    txt = _txt("to-18-14-speaking-times.pdf")
    first_item = txt.index("1. Antrag der Fraktion der AfD")
    assert "Begründung:" not in txt[:first_item] and "Aussprache:" not in txt[:first_item]
    assert txt.index("Begründung:") < txt.index("2. Aktuelle Debatte")  # TOP 1's own slot


def test_bw_gesetzblatt_law_text():
    # scraper-bw #27 kept only the signature page; the law is on page 1
    txt = _txt("gbl-2026-12.pdf")
    assert "Gesetz zur Änderung des Juristenausbildungsgesetzes" in txt
    assert "Dieses Gesetz tritt am Tag nach seiner Verkündung in Kraft." in txt
    assert "Seite 2 von 2" not in txt


@pytest.mark.xfail(strict=True, reason="#23: page-2 header in body, signature columns right first")
def test_bw_gesetzblatt_page_2():
    txt = _txt("gbl-2026-12.pdf")
    assert "Jahrgang 2026" not in txt
    assert txt.index("Strobl") < txt.index("Dr. Bayaz")


def test_bavarian_report():
    txt = _txt("drs-beschlussempfehlung-ablehnung.pdf")
    assert "Ablehnung empfohlen." in txt  # letter-spaced "A b l e h n u n g" collapsed
    assert "Parlamentsfragen" in txt  # soft hyphen at line end


def test_synopsis_report():
    d = Pipeline().run(SH_DIR / "drs-20-3769-synopsis.pdf")
    assert any(r.synopsis for p in d.pages if p.layout for r in p.layout.iter_regions())
    txt = _txt("drs-20-3769-synopsis.pdf")
    assert "Schleswig-Holsteinischer Landtag – 20.Wahlperiode" not in txt  # running header removed


def test_protocol_header_removed():
    assert "Protokollauszug" not in _txt("protokollauszug-24p.pdf")


def test_email_ligatures_kept():
    txt = _txt("email-attached-letter-ligatures.pdf")
    assert "künftig" in txt and "Schritte" in txt  # ligature components kept


def _txt(name):
    return render(sample(name), "txt")


@pytest.mark.ocr  # four of the five are scans; without OCR their text is empty and the test proves nothing
def test_footers_removed_from_samples():
    assert "WIRTSCHAFTSMACHT" not in _txt("scan-rotate-270-footer-logo.pdf")
    assert "WIRTSCHAFTSMACHT" not in _txt("scan-letter-continuation-page.pdf")
    assert "Landesvorstand" not in _txt("scan-reading-order.pdf")
    assert "Tagesordnungen der Vollversammlung" not in _txt("drs-beschlussempfehlung-ablehnung.pdf")
    assert "www.freie-wohlfahrtspflege-bayern.de" not in _txt("scan-statement-sidebar.pdf")


def test_bottom_of_page_content_kept():
    assert "Pfad der Vernunft" in _txt("protokollauszug-24p.pdf")
    assert "Sie streuen den Leuten Sand in die Augen" in _txt("protokollauszug-24p.pdf")
    assert "cc) Nummer 3 wird gestrichen." in _txt("drs-20-3769-synopsis.pdf")
    assert "Sehr geehrte Damen und Herren," in _txt("email-outlook-forwarded.pdf")
    d = sample("email-attached-letter-ligatures.pdf")
    assert sum(1 for b in d.blocks if b.kind.value == "footnote") >= 2
