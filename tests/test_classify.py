import re

import pytest

from pazufa_pdf_parser.classify import Classifier, ClassifierInput, Rule, guess_language
from pazufa_pdf_parser.model import DocType


def inp(text: str, **features) -> ClassifierInput:
    first = "\n".join(text.split("\n")[:20])
    return ClassifierInput(head=text, all=text, tail=text, first_lines=first, features=features)


LETTER = """Verband e.V. | Musterweg 5 | 80331 München
Bayerische Staatskanzlei
Franz-Josef-Strauß-Ring 1
80539 München
München, 16.07.2024
Stellungnahme zum Entwurf
Sehr geehrte Frau Muster,
vielen Dank für die Möglichkeit.
Mit freundlichen Grüßen
Max Mustermann"""

EMAIL = """Von: Thomas Schmid
An: Referat B6
Betreff: WG: Anhörung
Gesendet: Donnerstag, 6. März 2025 08:39
Sehr geehrter Herr Dr. Hirschberg,
anbei unsere Stellungnahme.
Mit freundlichen Grüßen"""

PRINT = """Bayerischer Landtag 19. Wahlperiode 17.07.2025 Drucksache 19/7613
Gesetzentwurf
der Staatsregierung
zur Änderung des Bayerischen Wassergesetzes
A) Problem
Text
B) Lösung
Text"""

PROTOCOL = """Plenarprotokoll 19/41
41. Plenum, 04.02.2025
Präsidentin Ilse Aigner: Ich rufe den Tagesordnungspunkt 3 auf.
Staatsminister Albert Füracker (Finanzen und Heimat): Herr Präsident!
(Beifall bei der CSU)
Andreas Winhart (AfD): Sehr geehrte Damen und Herren!
(Beifall bei der AfD)"""

STATUTE = """Gesetz über die Testverwaltung
Vom 1. Januar 2020 (GVBl. S. 1)
Der Landtag hat das folgende Gesetz beschlossen:
§ 1
Anwendungsbereich
§ 2
Begriffe
§ 3 Zuständigkeit
Dieses Gesetz tritt am 1. Februar 2020 in Kraft."""

JUDGMENT = """Verwaltungsgericht München
M 8 K 20.1234
Im Namen des Volkes
Urteil
In der Verwaltungsstreitsache
Tenor
Tatbestand
Entscheidungsgründe
Rechtsmittelbelehrung"""

CONTRACT = """Mietvertrag
zwischen
Erika Musterfrau
- nachfolgend „Vermieterin“ genannt -
und
Max Mustermann
- nachfolgend „Mieter“ genannt -
§ 1 Vertragsgegenstand
§ 2 Kündigung
Ort, Datum"""


@pytest.mark.parametrize(
    "text,expected,subtype",
    [
        (LETTER, DocType.LETTER, "statement"),
        (EMAIL, DocType.EMAIL, None),
        (PRINT, DocType.PARLIAMENTARY_PRINT, "bill"),
        (PROTOCOL, DocType.PLENARY_PROTOCOL, "full"),
        (STATUTE, DocType.STATUTE, "act"),
        (JUDGMENT, DocType.COURT_DECISION, "judgment"),
        (CONTRACT, DocType.CONTRACT, None),
    ],
)
def test_classification(text, expected, subtype):
    c = Classifier().classify_input(inp(text))
    assert c.doc_type is expected, c.scores
    assert c.subtype == subtype
    assert 0 < c.confidence <= 1
    assert c.evidence[expected.value]


def test_generic_for_unrelated_text():
    c = Classifier().classify_input(inp("Ein Kochrezept: Mehl, Zucker und Eier verrühren."))
    assert c.doc_type is DocType.GENERIC


def test_footer_mentioning_plenarprotokolle_is_not_a_protocol():
    text = (
        PRINT.replace("A) Problem", "Beschlussempfehlung")
        + "\nDrucksachen, Plenarprotokolle sowie die Tagesordnungen sind im Internet abrufbar. 25. Sitzung"
    )
    assert Classifier().classify_input(inp(text)).doc_type is DocType.PARLIAMENTARY_PRINT


def test_email_printout_of_letter_is_email():
    assert Classifier().classify_input(inp(EMAIL + "\n" + LETTER)).doc_type is DocType.EMAIL


def test_report_subtype_by_first_occurrence():
    text = "Drucksache 19/7613\n19. Wahlperiode\nBeschlussempfehlung und Bericht\ndes Ausschusses\nGesetzentwurf der Abgeordneten"
    c = Classifier().classify_input(inp(text))
    assert c.doc_type is DocType.PARLIAMENTARY_PRINT and c.subtype == "report"


def test_custom_rules_extend_classifier():
    rule = Rule(DocType.CONTRACT, "custom", 50.0, re.compile("GEHEIMWORT"))
    c = Classifier(extra_rules=[rule]).classify_input(inp(LETTER + "\nGEHEIMWORT"))
    assert c.doc_type is DocType.CONTRACT
    assert any("custom" in e for e in c.evidence["contract"])


def test_language_guess():
    assert guess_language("Der Bericht und die Empfehlung des Ausschusses ist nicht") == "de"
    assert guess_language("The report and the recommendation of the committee is") == "en"
    assert guess_language("12345") == "und"
