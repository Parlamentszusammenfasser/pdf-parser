import pytest

from pazufa_parser.sanitize import (
    clean_chars,
    collapse_letterspacing,
    fix_ocr_text,
    is_junk_line,
    is_line_structured,
    join_hyphenated,
    normalize_spaces,
    reflow_lines,
    sanitize_text,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ﬁnden und ﬂießen", "finden und fließen"),
        ("Ge­setz", "Gesetz"),  # soft hyphen inside word
        ("a​b﻿c", "abc"),  # zero-width chars
        ("A B C", "A B C"),  # exotic spaces
        (" Punkt", "• Punkt"),  # Symbol-font bullet from private use area
        ("Text(cid:12)mehr", "Textmehr"),
        ("Ctrl\x07char", "Ctrlchar"),
        ("Über", "Über"),  # NFC composition
    ],
)
def test_clean_chars(raw, expected):
    assert clean_chars(raw) == expected


def test_clean_chars_keeps_newlines():
    assert clean_chars("a\r\nb\rc") == "a\nb\nc"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A b l e h n u n g empfohlen", "Ablehnung empfohlen"),
        ("Z u s t i m m u n g", "Zustimmung"),
        ("u. a. und z. B.", "u. a. und z. B."),  # abbreviations are untouched
        ("a b c", "a b c"),  # too short to be letter-spacing
        ("Art 1 a b", "Art 1 a b"),
    ],
)
def test_collapse_letterspacing(raw, expected):
    assert collapse_letterspacing(raw) == expected


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("Parlaments-", "fragen und Integration", "Parlamentsfragen und Integration"),
        ("die CDU-", "Fraktion", "die CDU-Fraktion"),
        ("Aus-", "und Fortbildung", "Aus- und Fortbildung"),
        ("Kinderbildungs-", "oder Betreuungsgesetz", "Kinderbildungs- oder Betreuungsgesetz"),
        ("kein Trennstrich", "weiter", None),
        ("Zahl 3-", "4", None),  # hyphen after a digit is not a word division
    ],
)
def test_join_hyphenated(first, second, expected):
    assert join_hyphenated(first, second) == expected


def test_reflow_joins_wrapped_prose_and_dehyphenates():
    lines = [
        "Der Gesetzentwurf wurde dem Ausschuss für Umwelt und Verbraucherschutz",
        "federführend zugewiesen. Der Ausschuss für Verfassung, Recht, Parlaments-",
        "fragen und Integration hat den Gesetzentwurf endberaten.",
    ]
    out = reflow_lines(lines, [400, 400, 300], 400)
    assert "\n" not in out
    assert "Parlamentsfragen" in out


def test_reflow_keeps_address_lines():
    lines = ["Bayerische Staatskanzlei", "Frau Staatsrätin Muster", "Franz-Josef-Strauß-Ring 1", "80539 München"]
    assert is_line_structured(lines)
    assert reflow_lines(lines) == "\n".join(lines)


def test_reflow_keeps_label_lines():
    lines = ["CSU: Ablehnung", "FREIE WÄHLER: Ablehnung", "SPD: Zustimmung"]
    out = reflow_lines(lines, [100, 140, 100], 140)
    assert out.split("\n") == lines


def test_reflow_keeps_mail_header_lines():
    lines = ["Von: Thomas Schmid <t@example.org>", "An: Referat B6 <r@example.org>", "Betreff: Verbandsanhörung zum Gesetzentwurf der Staatsregierung"]
    assert reflow_lines(lines, [300, 280, 420], 420).count("\n") == 2


def test_normalize_spaces():
    assert normalize_spaces("a\t\tb   c ,d ( e )") == "a b c,d (e)"


@pytest.mark.parametrize("line,junk", [("___________", True), ("- . ' ,", True), ("§", False), ("Text", False), ("", True)])
def test_is_junk_line(line, junk):
    assert is_junk_line(line) is junk


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Zu 8 3 drittes Modernisierungsgesetz", "Zu § 3 drittes Modernisierungsgesetz"),
        ("Zu 87 Nr. 1 —- Änderungen", "Zu § 7 Nr. 1 – Änderungen"),
        ("gemäß 8 5 Abs. 2 BayBO", "gemäß § 5 Abs. 2 BayBO"),
        ("Gebäude bis 20 m? Brutto-Rauminhalt", "Gebäude bis 20 m² Brutto-Rauminhalt"),
        ("Wilfried’Mück", "Wilfried Mück"),
        ("zu 80 Prozent", "zu 80 Prozent"),  # genuine numbers stay
        ("am 8. Mai", "am 8. Mai"),
    ],
)
def test_fix_ocr_text(raw, expected):
    assert fix_ocr_text(raw) == expected


def test_sanitize_text_end_to_end():
    raw = "Erste Zeile mit Tren-\nnung und ﬁ-Ligatur.\n\n____________\n\nZweiter   Absatz."
    assert sanitize_text(raw) == "Erste Zeile mit Trennung und fi-Ligatur.\n\nZweiter Absatz."
