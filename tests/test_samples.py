"""Regression tests against real-world sample PDFs.

``tests/samples/by`` holds one Bavarian PDF per layout case, ``tests/samples/bw`` the
Baden-Württemberg PDFs that broke scraper-bw (see their READMEs). The older
problem PDFs in ``EXPECTED`` are not in the repository; point
``PAZUFA_SAMPLES_DIR`` at them to run those too::

    PAZUFA_SAMPLES_DIR=~/Nextcloud/projekte/pazufa/problempdfs-by uv run pytest -m samples
"""

import os
import re
from collections import Counter
from pathlib import Path

import pytest

from pazufa_pdf_parser import DocType, parse, render

pytestmark = pytest.mark.samples

BY_DIR = Path(__file__).parent / "samples" / "by"
# these have pages the parser OCRs; without tesseract their text is missing or incomplete
BY_OCR = {
    "drs-staatsvertrag-bilingual-rotated-maps.pdf",
    "letter-image-letterhead-ocr-merge.pdf",
    "scan-garbled-font.pdf",
    "scan-letter.pdf",
    "scan-reading-order.pdf",
    "scan-rotate-270.pdf",
    "scan-rotate-90.pdf",
    "statement-ti-ligature-mixed-scan.pdf",
}
BW_DIR = Path(__file__).parent / "samples" / "bw"
BW_OCR = {"drs-17-1104-garbled-146p.pdf", "drs-17-1201-ascii-shift.pdf", "drs-17-6014-garbled-annex.pdf"}
BW_SLOW = {"drs-17-1104-garbled-146p.pdf"}  # 131 OCR pages, ~30 s


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

EXPECTED = {
    "0000000003.pdf": (DocType.LETTER, "statement"),
    "0000000041.pdf": (DocType.LETTER, None),
    "0000005048.pdf": (DocType.PARLIAMENTARY_PRINT, "report"),
    "0000010143.pdf": (DocType.LETTER, "statement"),
    "0000010184.pdf": (DocType.LETTER, None),
    "0000010201.pdf": (DocType.EMAIL, None),
    "0000010446.pdf": (DocType.EMAIL, None),
    "041_PL_004_gesetzentwurf-4721.pdf": (DocType.PLENARY_PROTOCOL, "excerpt"),
    "drucksache-20-03769.pdf": (DocType.PARLIAMENTARY_PRINT, "report"),
}

_cache: dict[str, object] = {}


def sample(name):
    roots = [BY_DIR, BW_DIR]
    if env := os.environ.get("PAZUFA_SAMPLES_DIR"):
        roots.append(Path(env).expanduser())
    path = next((r / name for r in roots if (r / name).exists()), None)
    if path is None:
        pytest.skip(f"{name} not in samples dir")
    if name not in _cache:
        _cache[name] = parse(path)
    return _cache[name]


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_classification(name, expected):
    d = sample(name)
    assert (d.doc_type, d.classification.subtype) == expected
    assert not [i for i in d.issues if i.severity == "error"]


@pytest.mark.parametrize("name", [*EXPECTED, *BY_SAMPLES, *BW_SAMPLES])
def test_all_formats_render(name, akn_schema):
    from lxml import etree

    d = sample(name)
    assert not [i for i in d.issues if i.severity == "error"]
    for fmt in ("raw", "txt", "html", "json"):
        assert render(d, fmt).strip()
    assert akn_schema.validate(etree.fromstring(render(d, "legalxml").encode()))


def test_clean_drucksache():
    # best case: a born-digital BY Drucksache whose text must come out exactly clean
    txt = render(sample("drs-clean.pdf"), "txt")
    assert txt.count("Drucksache 19/9342") == 1  # running header of pp. 2-3 removed
    assert "Seite" not in txt
    assert "Drucksachen, Plenarprotokolle" not in txt  # page-1 footer removed
    assert txt.rstrip().endswith("I. Vizepräsident")
    assert "Dieses Gesetz tritt am 1. Januar 2026 in Kraft." in txt


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


@pytest.mark.parametrize(
    "name,sources,anchors",
    [
        ("drs-17-0273-clean.pdf", {"text": 4}, ["Ausgegeben: 25.6.2021", "A. Zielsetzung"]),
        pytest.param(
            "drs-17-1201-ascii-shift.pdf",
            {"text": 1, "ocr": 4},
            ["Ausgegeben: 7.1.2022", "Änderungsantrag"],
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
    # BW annexes embed fonts with broken ToUnicode maps (ASCII +29 shift, Latin-Extended mojibake).
    # "Ausgegeben: …" sits in the page-1 footer, which stays in the body until #22 is decided.
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
        assert f"17/1201-{p.number - 1}" in "\n".join(b.text for b in p.blocks)


@pytest.mark.xfail(strict=True, reason="#22: two-column page-1 footer read line by line")
def test_bw_drucksache_footer():
    txt = _txt("drs-17-0273-clean.pdf")
    assert "Recyclingpapier" not in txt or "Plenarprotokolle sind im Internet abrufbar" in txt


def test_bw_protocol_page_numbers():
    d = sample("plpr-18-10.pdf")
    numbers = [[b.text for b in p.furniture if b.kind.value == "page_number"] for p in d.pages]
    assert numbers[2:] == [[str(n)] for n in range(259, 306)]
    assert "Präsident Thomas Strobl: Guten Morgen" in render(d, "txt")


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
    d = sample("0000005048.pdf")
    f = d.fields["print"]
    assert f["number"] == "19/7613" and f["date"] == "2025-07-17"
    assert f["title"] == "zur Änderung des Bayerischen Wassergesetzes"
    assert f["recommendation"] == "Ablehnung"
    assert [r["name"] for r in f["rapporteurs"]] == ["Christian Hierneis", "Thomas Holz"]
    assert f["votes"][0]["results"]["SPD"] == "Zustimmung"
    txt = render(d, "txt")
    assert "Ablehnung empfohlen." in txt  # letter-spaced "A b l e h n u n g" collapsed
    assert "Parlamentsfragen" in txt  # soft hyphen at line end


def test_synopsis_report():
    d = sample("drucksache-20-03769.pdf")
    assert d.fields["print"]["parliament"] == "Schleswig-Holsteinischer Landtag"
    assert d.synopsis and d.synopsis[0]["right_label"] == "Ausschussvorschlag"
    txt = render(d, "txt")
    assert "Schleswig-Holsteinischer Landtag – 20.Wahlperiode" not in txt  # running header removed


def test_protocol():
    d = sample("041_PL_004_gesetzentwurf-4721.pdf")
    p = d.fields["protocol"]
    assert p["session"] == 41 and p["date"] == "2025-02-04"
    names = {s["name"] for s in p["speakers"]}
    assert {"Tobias Reiß", "Albert Füracker", "Andreas Winhart", "Ruth Waldmann"} <= names
    assert "Protokollauszug" not in render(d, "txt")


def test_email_with_attached_letter():
    d = sample("0000010446.pdf")
    e = d.fields["email"]
    assert e["subject_clean"] == "Stellungnahme der GEW - BayKiBiG"
    assert e["from"]["email"] == "mario.schwandt@gew-bayern.de"
    assert "attached_letter" in e
    txt = render(d, "txt")
    assert "künftig" in txt and "Schritte" in txt  # ligature components kept


def test_scanned_letter_fields():
    d = sample("0000000003.pdf")
    f = d.fields["letter"]
    assert f["recipient"]["postal_code"] == "81602"
    assert f["date"] == "2023-08-16"
    assert f["subject"] == "Gesetz zur Änderung des Pflegendenvereinigungsgesetzes"


def _txt(name):
    return render(sample(name), "txt")


def test_footers_removed_from_samples():
    assert "WIRTSCHAFTSMACHT" not in _txt("0000000041.pdf")
    assert "WIRTSCHAFTSMACHT" not in _txt("0000010184.pdf")
    assert "Landesvorstand" not in _txt("0000010143.pdf")
    assert "Tagesordnungen der Vollversammlung" not in _txt("0000005048.pdf")
    assert "www.freie-wohlfahrtspflege-bayern.de" not in _txt("0000000003.pdf")


def test_bottom_of_page_content_kept():
    assert "Pfad der Vernunft" in _txt("041_PL_004_gesetzentwurf-4721.pdf")
    assert "Sie streuen den Leuten Sand in die Augen" in _txt("041_PL_004_gesetzentwurf-4721.pdf")
    assert "cc) Nummer 3 wird gestrichen." in _txt("drucksache-20-03769.pdf")
    assert "Sehr geehrte Damen und Herren," in _txt("0000010201.pdf")
    d = sample("0000010446.pdf")
    assert sum(1 for b in d.body_blocks if b.kind.value == "footnote") >= 2
