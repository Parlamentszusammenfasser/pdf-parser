from pazufa_pdf_parser.fields.common import extract_entities, find_dates
from pazufa_pdf_parser.fields.email import _finalize, _split_addresses, parse_header_lines
from pazufa_pdf_parser.fields.legal import parse_legal_texts
from pazufa_pdf_parser.fields.letter import split_return_address


class TestEntities:
    def test_dates(self):
        ds = find_dates("am 17.07.2025, am 1. Oktober 2025 und 2025-12-09 sowie 31.02.2025")
        assert [d["iso"] for d in ds] == ["2025-07-17", "2025-10-01", "2025-12-09"]

    def test_two_digit_year(self):
        assert find_dates("Brief vom 3.4.24")[0]["iso"] == "2024-04-03"

    def test_entities(self):
        text = (
            "Tel. 089 235003-11\nFax: +49 89 235003-71\nE-Mail: T.Schmid@bauindustrie-bayern.de\n"
            "www.bauindustrie-bayern.de\nIBAN DE89 3704 0044 0532 0130 00\nBIC COBADEFFXXX\n"
            "vgl. Drs. 19/6369 und Drucksache 20/3589; Az.: B II 6 - 1356\n"
            "Nach § 3 Abs. 2 Satz 1 BayBO und Art. 57 Abs. 1 Nr. 18 BayBO sowie §§ 1, 2 BGB."
        )
        e = extract_entities(text)
        assert {"type": "phone", "number": "089 235003-11"} in e["phones"]
        assert any(p["type"] == "fax" for p in e["phones"])
        assert e["emails"] == ["T.Schmid@bauindustrie-bayern.de"]
        assert e["urls"] == ["www.bauindustrie-bayern.de"]
        assert e["ibans"] == [{"iban": "DE89370400440532013000", "valid": True}]
        assert e["bics"] == ["COBADEFFXXX"]
        assert e["printed_matter"] == ["19/6369", "20/3589"]
        assert "§ 3 Abs. 2 S. 1 BayBO" in e["legal_references"] or "§ 3 Abs. 2 Satz 1 BayBO" in e["legal_references"]
        assert "Art. 57 Abs. 1 Nr. 18 BayBO" in e["legal_references"]
        assert any(r.startswith("§§ 1, 2") for r in e["legal_references"])
        assert e["file_numbers"][0].startswith("B II 6")

    def test_invalid_iban_flagged(self):
        e = extract_entities("IBAN DE00 3704 0044 0532 0130 00")
        assert e["ibans"][0]["valid"] is False

    def test_empty(self):
        assert extract_entities("") == {}


class TestEmail:
    def test_header_parsing_with_continuations(self):
        lines = [
            "Von:\tThomas Schmid",
            "An:\tReferat BII6 (StK)",
            "Betreff:\tWG: Verbandsanhörung - Schreiben vom",
            "21.02.2025 - Unser Az.: B II 6",
            "Datum:\tDonnerstag, 6. März 2025 08:39:54",
            "Anlagen:\timage001.png",
            "Anschreiben.pdf",
            "Sehr geehrter Herr Dr. Hirschberg,",
        ]
        h, n = parse_header_lines(lines, [1] * 7 + [2])
        assert n == 7
        f = _finalize(h)
        assert f["subject_clean"].endswith("Unser Az.: B II 6")
        assert f["forwarded"] is True
        assert f["datetime"] == "2025-03-06T08:39:54"
        assert f["attachments"] == ["image001.png", "Anschreiben.pdf"]

    def test_address_splitting(self):
        addrs = _split_addresses("Referat-V3 (StMAS) <Referat-V3@stmas.bayern.de> Hilger Uhlenbrock <h.u@gew.de>; x@y.de")
        assert [a["email"] for a in addrs] == ["Referat-V3@stmas.bayern.de", "h.u@gew.de", "x@y.de"]
        assert addrs[1]["name"] == "Hilger Uhlenbrock"
        assert _split_addresses("Referat BII6 (StK)") == [{"name": "Referat BII6 (StK)"}]


class TestLegalStructure:
    def test_statute_hierarchy(self):
        items = [
            ("§ 1", True),
            ("Anwendungsbereich", True),
            ("(1) Dieses Gesetz gilt für alle.", False),
            ("(2) Es gilt nicht für:", False),
            ("1. Behörden,", False),
            ("2. Gerichte, und zwar", False),
            ("a) Amtsgerichte,", False),
            ("aa) in Bayern", False),
            ("b) Landgerichte.", False),
            ("§ 2 Inkrafttreten", True),
            ("Dieses Gesetz tritt morgen in Kraft.", False),
        ]
        roots = parse_legal_texts(items)
        assert [r.num for r in roots] == ["1", "2"]
        s1 = roots[0]
        assert s1.kind == "section" and s1.heading == "Anwendungsbereich"
        assert [c.num for c in s1.children] == ["1", "2"]
        points = s1.children[1].children
        assert [p.num for p in points] == ["1", "2"]
        items_ = points[1].children
        assert [i.num for i in items_] == ["a", "b"]
        assert items_[0].children[0].kind == "subitem" and items_[0].children[0].num == "aa"
        assert roots[1].heading == "Inkrafttreten" and roots[1].text == ["Dieses Gesetz tritt morgen in Kraft."]

    def test_quoted_amendment_is_not_structure(self):
        items = [
            ("Artikel 1", True),
            ("Änderung des Testgesetzes", True),
            ("1. Art. 2 erhält folgende Fassung:", False),
            ("„Art. 2", False),
            ("(1) Zuständig ist das Landesamt.", False),
            ("(2) Weiteres regelt die Verordnung.“", False),
            ("2. Art. 3 wird aufgehoben.", False),
        ]
        roots = parse_legal_texts(items)
        art = roots[0]
        assert art.kind == "article" and art.heading == "Änderung des Testgesetzes"
        assert [p.num for p in art.children] == ["1", "2"]
        assert len(art.children[0].text) == 4  # intro + 3 quoted paragraphs
        assert not art.children[0].children

    def test_reference_is_not_a_heading(self):
        roots = parse_legal_texts([("§ 3 Abs. 2 wird wie folgt geändert:", False)])
        assert roots[0].kind == "text"

    def test_text_before_structure(self):
        roots = parse_legal_texts([("Vorspruch", False), ("§ 1", True)])
        assert roots[0].kind == "text" and roots[1].kind == "section"


def test_return_address_split():
    assert split_return_address("Freie Wohlfahrtspflege Bayern | Lessingstraße 1 | 80336 München") == [
        "Freie Wohlfahrtspflege Bayern",
        "Lessingstraße 1",
        "80336 München",
    ]
    assert split_return_address("Ein normaler Satz ohne Adresse") is None
