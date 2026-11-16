from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from pazufa_pdf_parser import OcrMode, ParseOptions  # noqa: E402
from pdfgen import T, make_pdf, paragraph  # noqa: E402

NO_OCR = ParseOptions(ocr=OcrMode.NEVER)


def pytest_configure(config):
    config.addinivalue_line("markers", "ocr: needs a working tesseract installation with German data")
    config.addinivalue_line("markers", "samples: runs against real sample PDFs in tests/samples")
    config.addinivalue_line("markers", 'slow: takes more than ~10 s (deselect with -m "not slow")')


def _has_tesseract() -> bool:
    from pazufa_pdf_parser._pipeline.extract.ocr import tesseract_languages

    try:
        return "deu" in tesseract_languages()
    except Exception:
        return False


HAS_TESSERACT = _has_tesseract()
HAS_QPDF = shutil.which("qpdf") is not None


def pytest_collection_modifyitems(config, items):
    skip_ocr = pytest.mark.skip(reason="tesseract with 'deu' not available")
    for item in items:
        if "ocr" in item.keywords and not HAS_TESSERACT:
            item.add_marker(skip_ocr)


# --------------------------------------------------------------------------- synthetic documents

BODY1 = [
    "wir bedanken uns für die Möglichkeit, zum Entwurf des Gesetzes zur Ände-",
    "rung des Testgesetzes Stellung nehmen zu können. Der Verband begrüßt die",
    "vorgesehene Vereinfachung der Verfahren ausdrücklich, sieht aber in eini-",
    "gen Punkten noch Verbesserungsbedarf, den wir im Folgenden darstellen.",
]
BODY2 = [
    "Insbesondere die Regelung in § 3 Abs. 2 Satz 1 BayBO sollte überarbeitet",
    "werden, da sie in der Praxis zu erheblichen Unsicherheiten führt. Auch",
    "Art. 57 Abs. 1 Nr. 18 BayBO bedarf einer Klarstellung.",
]


def letter_pages() -> list[list[T]]:
    p1: list[T] = []
    p1 += [T(330, 40, "Verband der Testbetriebe e.V.", 16, True)]
    p1 += [T(70, 140, "Verband der Testbetriebe e.V. | Musterweg 5 | 80331 München", 7)]
    p1 += paragraph(
        70,
        160,
        [
            "Bayerisches Staatsministerium",
            "für Testangelegenheiten",
            "Frau Ministerialrätin Erika Muster",
            "Postfach 22 00 11",
            "80535 München",
        ],
        11,
    )
    # sidebar
    p1 += paragraph(
        420,
        140,
        [
            "Verband der Testbetriebe e.V.",
            "Musterweg 5",
            "80331 München",
            "Tel. 089 123456-0",
            "Fax 089 123456-99",
            "info@testverband.de",
        ],
        8,
        1.4,
    )
    p1 += paragraph(420, 225, ["Bankverbindung", "IBAN DE89 3704 0044 0532 0130 00", "BIC COBADEFFXXX"], 8, 1.4)
    p1 += [T(420, 280, "München, 16.07.2024", 11)]
    p1 += [T(70, 320, "Stellungnahme zum Entwurf eines Testgesetzes", 11, True)]
    p1 += [T(70, 355, "Sehr geehrte Frau Muster,", 11)]
    p1 += paragraph(70, 385, BODY1, 11)
    p1 += paragraph(70, 455, BODY2, 11)
    p1 += [T(70, 800, "Verband der Testbetriebe e.V. · Registergericht München VR 12345", 7)]
    p2: list[T] = []
    p2 += [T(290, 40, "- 2 -", 10)]
    p2 += paragraph(
        70,
        80,
        ["Wir würden uns freuen, wenn unsere Anregungen im weiteren Verfahren be-", "rücksichtigt werden könnten."],
        11,
    )
    p2 += [T(70, 130, "Mit freundlichen Grüßen", 11)]
    p2 += [T(70, 175, "Dr. Max Mustermann", 11), T(70, 190, "Hauptgeschäftsführer", 11)]
    p2 += [T(70, 800, "Verband der Testbetriebe e.V. · Registergericht München VR 12345", 7)]
    return [p1, p2]


def bill_pages() -> list[list[T]]:
    pages = []
    p1 = [
        T(70, 50, "Bayerischer Landtag", 11),
        T(250, 50, "19. Wahlperiode", 11),
        T(420, 50, "Drucksache 19/1234", 11, True),
        T(420, 66, "01.02.2025", 11),
        T(70, 110, "Gesetzentwurf", 16, True),
        T(70, 135, "der Staatsregierung", 12, True),
        T(70, 165, "zur Änderung des Bayerischen Testgesetzes", 12, True),
        T(70, 210, "A) Problem", 11, True),
    ]
    p1 += paragraph(
        70,
        230,
        [
            "Das geltende Testgesetz enthält veraltete Regelungen, die den Vollzug",
            "unnötig erschweren und angepasst werden müssen.",
        ],
        11,
    )
    p1 += [T(70, 280, "B) Lösung", 11, True)]
    p1 += paragraph(70, 300, ["Die Regelungen werden vereinfacht."], 11)
    p1 += [T(70, 340, "C) Alternativen", 11, True), T(70, 360, "Keine", 11)]
    pages.append(p1)

    def hdr(n):
        return [
            T(70, 30, "Drucksache 19/1234", 9),
            T(250, 30, "Bayerischer Landtag – 19. Wahlperiode", 9),
            T(500, 30, f"Seite {n}", 9),
        ]

    p2 = hdr(2) + [
        T(170, 80, "Gesetz zur Änderung des Bayerischen Testgesetzes", 12, True),
        T(70, 120, "§ 1", 11, True),
        T(70, 136, "Änderung des Testgesetzes", 11, True),
    ]
    p2 += paragraph(
        70,
        160,
        ["Das Bayerische Testgesetz (BayTestG) vom 1. Januar 2000 (GVBl. S. 1) wird", "wie folgt geändert:"],
        11,
    )
    p2 += paragraph(70, 200, ["1. Art. 1 wird wie folgt geändert:"], 11)
    p2 += paragraph(85, 220, ["a) Abs. 1 wird aufgehoben.", "b) In Abs. 2 werden die Wörter „bis zu“ gestrichen."], 11)
    p2 += paragraph(70, 265, ["2. Art. 2 erhält folgende Fassung:"], 11)
    p2 += paragraph(85, 285, ["„Art. 2", "Zuständigkeit", "(1) Zuständig ist das Landesamt.“"], 11)
    p2 += [T(70, 360, "§ 2", 11, True), T(70, 376, "Inkrafttreten", 11, True)]
    p2 += paragraph(
        70,
        400,
        [
            "(1) Dieses Gesetz tritt am 1. Januar 2026 in Kraft.",
            "(2) Mit Ablauf des 31. Dezember 2025 tritt das Altgesetz außer Kraft.",
        ],
        11,
        1.8,
    )
    p2 += [T(70, 470, "Begründung:", 11, True)]
    p2 += paragraph(70, 490, ["A) Allgemeiner Teil", "Die Änderungen dienen der Entbürokratisierung."], 11)
    pages.append(p2)
    return pages


def email_pages() -> list[list[T]]:
    p = [
        T(70, 60, "Von:", 10, True),
        T(170, 60, "Thomas Schmid <t.schmid@example.org>", 10),
        T(70, 74, "An:", 10, True),
        T(170, 74, "Referat B6 <referat@stk.example.de>; Anna Bauer <a.bauer@example.de>", 10),
        T(70, 88, "Cc:", 10, True),
        T(170, 88, "info@example.org", 10),
        T(70, 102, "Betreff:", 10, True),
        T(170, 102, "WG: Verbandsanhörung - Drittes Modernisierungsgesetz", 10),
        T(70, 116, "Datum:", 10, True),
        T(170, 116, "Donnerstag, 6. März 2025 08:39:54", 10),
        T(70, 130, "Anlagen:", 10, True),
        T(170, 130, "Stellungnahme.pdf", 10),
        T(170, 144, "Gesetzentwurf.pdf", 10),
        T(70, 190, "Sehr geehrter Herr Dr. Hirschberg,", 11),
    ]
    p += paragraph(
        70,
        220,
        ["anbei übersenden wir Ihnen unsere Anmerkungen zum Gesetzentwurf.", "Wir bitten um Berücksichtigung."],
        11,
    )
    p += [
        T(70, 280, "Mit freundlichen Grüßen", 11),
        T(70, 296, "Thomas Schmid", 11),
        T(70, 312, "Hauptgeschäftsführer", 11),
    ]
    p += [
        T(70, 360, "Von: Vertretung <vertretung@stk.example.de>", 10),
        T(70, 374, "Gesendet: Freitag, 21. Februar 2025 12:14", 10),
        T(70, 388, "An: Infopostfach <info@example.org>", 10),
        T(70, 402, "Betreff: Verbandsanhörung - Drittes Modernisierungsgesetz", 10),
        T(70, 440, "Sehr geehrte Damen und Herren,", 11),
        T(70, 460, "in der Anlage erhalten Sie den Entwurf.", 11),
    ]
    return [p]


def protocol_pages() -> list[list[T]]:
    pages = []
    for n in range(1, 3):
        p = [
            T(70, 30, "Plenarprotokoll 19/41", 9),
            T(300, 30, "Bayerischer Landtag – 19. Wahlperiode", 9),
            T(520, 30, str(n), 9),
        ]
        if n == 1:
            p += [T(70, 70, "41. Plenum, 04.02.2025", 11)]
            p += [
                T(70, 100, "Präsidentin Ilse Aigner:", 11, True),
                T(205, 100, "Ich rufe den Tagesordnungspunkt 3 b auf:", 11),
            ]
            p += [T(70, 125, "Gesetzentwurf der Staatsregierung zur Änderung des Testgesetzes (Drs. 19/4721)", 11)]
            p += [
                T(70, 155, "Staatsminister Albert Füracker (Finanzen und Heimat):", 11, True),
                T(375, 155, "Herr Präsident, liebe", 11),
            ]
            p += paragraph(
                70,
                170,
                [
                    "Kolleginnen und Kollegen! Wir debattieren heute über ein Gesetz, das sehr",
                    "technisch klingt, aber wichtige Folgen hat.",
                ],
                11,
            )
            p += [T(70, 215, "(Beifall bei der CSU)", 11)]
            p += [
                T(70, 240, "Präsidentin Ilse Aigner:", 11, True),
                T(205, 240, "Vielen Dank. – Nächster Redner ist Herr Winhart.", 11),
            ]
            p += [
                T(70, 265, "Andreas Winhart (AfD):", 11, True),
                T(200, 265, "Sehr geehrte Frau Präsidentin! Dieser Entwurf", 11),
            ]
            p += paragraph(70, 280, ["greift zu kurz und wird den Problemen der Krankenhäuser nicht gerecht."], 11)
        else:
            p += paragraph(70, 70, ["Wir lehnen ihn daher ab."], 11)
            p += [T(70, 100, "(Beifall bei der AfD)", 11)]
            p += [T(70, 125, "Präsidentin Ilse Aigner:", 11, True), T(205, 125, "Die Aussprache ist geschlossen.", 11)]
        pages.append(p)
    return pages


def judgment_pages() -> list[list[T]]:
    p = [
        T(70, 50, "Verwaltungsgericht München", 12, True),
        T(70, 70, "Az.: M 8 K 20.1234", 11),
        T(250, 110, "Im Namen des Volkes", 13, True),
        T(280, 135, "Urteil", 13, True),
        T(70, 165, "In der Verwaltungsstreitsache", 11),
        T(70, 185, "Max Mustermann, Musterweg 1, 80331 München", 11),
        T(70, 200, "- Kläger -", 11),
        T(70, 225, "gegen", 11),
        T(70, 245, "Freistaat Bayern", 11),
        T(70, 260, "- Beklagter -", 11),
        T(70, 285, "wegen Baugenehmigung", 11),
        T(70, 310, "erlässt das Verwaltungsgericht München am 12. März 2024 folgendes", 11),
        T(270, 340, "Tenor", 12, True),
        T(70, 365, "I. Die Klage wird abgewiesen.", 11),
        T(70, 380, "II. Der Kläger trägt die Kosten des Verfahrens.", 11),
        T(260, 410, "Tatbestand", 12, True),
        T(70, 435, "Der Kläger begehrt die Erteilung einer Baugenehmigung für ein Wohnhaus.", 11),
        T(240, 465, "Entscheidungsgründe", 12, True),
        T(70, 490, "Die zulässige Klage ist unbegründet. Der Kläger hat keinen Anspruch.", 11),
        T(220, 520, "Rechtsmittelbelehrung", 12, True),
        T(70, 545, "Gegen dieses Urteil steht den Beteiligten die Berufung zu.", 11),
    ]
    return [p]


def contract_pages() -> list[list[T]]:
    p = [
        T(250, 50, "Mietvertrag", 16, True),
        T(70, 90, "zwischen", 11),
        T(70, 110, "Erika Musterfrau, Musterstraße 1, 80331 München", 11),
        T(70, 125, "- nachfolgend „Vermieterin“ genannt -", 11),
        T(70, 150, "und", 11),
        T(70, 170, "Max Mustermann, Beispielweg 2, 80333 München", 11),
        T(70, 185, "- nachfolgend „Mieter“ genannt -", 11),
        T(70, 215, "wird folgender Vertrag geschlossen:", 11),
        T(70, 245, "§ 1 Vertragsgegenstand", 11, True),
        T(70, 265, "(1) Vermietet wird die Wohnung im 2. OG links.", 11),
        T(70, 280, "(2) Die Wohnfläche beträgt 65 m².", 11),
        T(70, 310, "§ 2 Mietzeit", 11, True),
        T(70, 330, "Das Mietverhältnis beginnt am 01.03.2025 und läuft auf unbestimmte Zeit.", 11),
        T(70, 360, "§ 3 Kündigung", 11, True),
        T(70, 380, "Die Kündigung bedarf der Schriftform.", 11),
        T(70, 450, "München, 15.02.2025", 11),
        T(70, 480, "Ort, Datum, Unterschrift Vermieterin", 9),
        T(330, 480, "Ort, Datum, Unterschrift Mieter", 9),
    ]
    return [p]


SYN_LEFT = [
    "Artikel 1",
    "Änderung des Stiftungsgesetzes",
    "Das Stiftungsgesetz vom 30. Mai 2023 (GVOBl.",
    "S. 279) wird wie folgt geändert:",
    "1. Die Inhaltsübersicht wird wie folgt geän-",
    "dert:",
    "a) Die Angabe zu § 6 wird durch die Anga-",
    "be „§ 6 Anzeigepflichten“ ersetzt.",
    "b) Die Angabe zu § 13 wird gestrichen.",
    "2. § 6 wird wie folgt geändert:",
    "a) Absatz 1 wird aufgehoben.",
]
SYN_RIGHT = [
    "Artikel 1",
    "Änderung des Stiftungsgesetzes",
    "Das Stiftungsgesetz vom 30. Mai 2023 (GVOBl.",
    "S. 279) wird wie folgt geändert:",
    "1. Die Inhaltsübersicht wird wie folgt geän-",
    "dert:",
    "a) Die Angabe zu § 6 wird durch die An-",
    "gabe „§ 6 Anzeigepflichten“ ersetzt.",
    "b) unverändert",
    "2. § 6 wird wie folgt geändert:",
    "a) Absatz 1 erhält folgende Fassung.",
]


def synopsis_pages() -> list[list[T]]:
    p = [
        T(70, 40, "SCHLESWIG-HOLSTEINISCHER LANDTAG", 12, True),
        T(400, 40, "Drucksache 20/3769", 12, True),
        T(70, 56, "20. Wahlperiode", 11),
        T(70, 90, "Bericht und Beschlussempfehlung", 14, True),
        T(70, 110, "des Innen- und Rechtsausschusses", 12, True),
        T(70, 150, "Gesetzentwurf der Fraktionen:", 10, True),
        T(310, 150, "Ausschussvorschlag:", 10, True),
    ]
    p += paragraph(70, 180, SYN_LEFT, 10, 1.4)
    p += paragraph(310, 180, SYN_RIGHT, 10, 1.4)
    return [p]


COL_LEFT = [
    "Die erste Spalte beginnt mit einem Satz,",
    "der über mehrere Zeilen läuft und erst am",
    "Ende der Spalte abgeschlossen wird. Dies",
    "ist der Text der linken Spalte, der vor",
    "der rechten Spalte gelesen werden muss.",
]
COL_RIGHT = [
    "Völlig anderer Inhalt steht rechts: Hier",
    "geht es um Zuständigkeiten der Behörden,",
    "die Finanzierung von Vorhaben und die",
    "zeitliche Abfolge der Umsetzungsschritte",
    "im kommenden Haushaltsjahr.",
]


def two_column_pages() -> list[list[T]]:
    p = [T(70, 50, "Mitteilungsblatt der Testgemeinde", 16, True)]
    p += paragraph(70, 100, COL_LEFT, 10, 1.4)
    p += paragraph(320, 100, COL_RIGHT, 10, 1.4)
    p += paragraph(
        70, 220, ["Ein abschließender Absatz über die volle Breite der Seite schließt diesen Artikel ab."], 10
    )
    return [p]


@pytest.fixture(scope="session")
def letter_pdf() -> bytes:
    return make_pdf(letter_pages())


@pytest.fixture(scope="session")
def bill_pdf() -> bytes:
    return make_pdf(bill_pages())


@pytest.fixture(scope="session")
def email_pdf() -> bytes:
    return make_pdf(email_pages())


@pytest.fixture(scope="session")
def protocol_pdf() -> bytes:
    return make_pdf(protocol_pages())


@pytest.fixture(scope="session")
def judgment_pdf() -> bytes:
    return make_pdf(judgment_pages())


@pytest.fixture(scope="session")
def contract_pdf() -> bytes:
    return make_pdf(contract_pages())


@pytest.fixture(scope="session")
def synopsis_pdf() -> bytes:
    return make_pdf(synopsis_pages())


@pytest.fixture(scope="session")
def two_column_pdf() -> bytes:
    return make_pdf(two_column_pages())


@pytest.fixture(scope="session")
def parsed(letter_pdf, bill_pdf, email_pdf, protocol_pdf, judgment_pdf, contract_pdf, synopsis_pdf, two_column_pdf):
    """All synthetic documents parsed once (text layer only)."""
    from pazufa_pdf_parser import parse

    srcs = {
        "letter": letter_pdf,
        "bill": bill_pdf,
        "email": email_pdf,
        "protocol": protocol_pdf,
        "judgment": judgment_pdf,
        "contract": contract_pdf,
        "synopsis": synopsis_pdf,
        "two_column": two_column_pdf,
    }
    return {k: parse(v, NO_OCR) for k, v in srcs.items()}
