import json
from html.parser import HTMLParser

import pytest

from pazufa_parser import UnknownFormatError, available_formats, register_renderer, render
from pazufa_parser.render.legalxml import AKN_NS

ALL_DOCS = ["letter", "bill", "email", "protocol", "judgment", "contract", "synopsis", "two_column"]


def test_formats_registered():
    assert {"raw", "txt", "html", "legalxml", "json"} <= set(available_formats())


def test_unknown_format(parsed):
    with pytest.raises(UnknownFormatError):
        render(parsed["letter"], "pdf")


def test_custom_renderer(parsed):
    register_renderer("upper", lambda d: render(d, "txt").upper(), "up.txt")
    try:
        assert "SEHR GEEHRTE" in render(parsed["letter"], "upper")
    finally:
        from pazufa_parser.render import _REGISTRY

        _REGISTRY.pop("upper", None)


@pytest.mark.parametrize("name", ALL_DOCS)
def test_raw_contains_everything(parsed, name):
    d = parsed[name]
    raw = render(d, "raw")
    words = {w.text for p in d.pages for w in p.words}
    missing = [w for w in words if w not in raw]
    assert not missing


def test_raw_keeps_furniture_and_page_breaks(parsed):
    raw = render(parsed["letter"], "raw")
    assert "- 2 -" in raw and "Registergericht" in raw
    assert raw.count("\f") == 1


@pytest.mark.parametrize("name", ALL_DOCS)
def test_txt_is_clean(parsed, name):
    txt = render(parsed[name], "txt")
    assert txt.endswith("\n")
    assert "\t" not in txt and "\f" not in txt and "\n\n\n" not in txt
    assert "  " not in txt


@pytest.mark.parametrize("name", ALL_DOCS)
def test_json_roundtrip(parsed, name):
    data = json.loads(render(parsed[name], "json"))
    assert data["classification"]["doc_type"] == str(parsed[name].doc_type)
    assert data["pages"] and all("blocks" in p for p in data["pages"])
    assert data["sha256"] == parsed[name].sha256


class _Checker(HTMLParser):
    VOID = {"meta", "br", "img", "hr", "link", "input"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.tags = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}>, open: {self.stack[-3:]}")
        else:
            self.stack.pop()


@pytest.mark.parametrize("name", ALL_DOCS)
def test_html_well_formed(parsed, name):
    html = render(parsed[name], "html")
    c = _Checker()
    c.feed(html)
    assert not c.errors and not c.stack
    assert html.startswith("<!DOCTYPE html>")


def test_html_columns_and_synopsis(parsed):
    assert 'class="cols"' in render(parsed["two_column"], "html")
    syn = render(parsed["synopsis"], "html")
    assert 'class="synopsis"' in syn
    # aligned rows: left and right cell per row
    assert syn.count('<div class="l">') == syn.count('<div class="r">') > 3


def test_html_escapes(parsed):
    html = render(parsed["email"], "html")
    assert "&lt;t.schmid@example.org&gt;" in html


@pytest.mark.parametrize("name", ALL_DOCS)
def test_legalxml_validates_against_akn_schema(parsed, akn_schema, name):
    from lxml import etree

    xml = render(parsed[name], "legalxml")
    doc = etree.fromstring(xml.encode())
    ok = akn_schema.validate(doc)
    assert ok, "\n".join(str(e) for e in list(akn_schema.error_log)[:5])


@pytest.mark.parametrize(
    "name,element",
    [
        ("letter", "doc"),
        ("bill", "bill"),
        ("email", "doc"),
        ("protocol", "debate"),
        ("judgment", "judgment"),
        ("contract", "doc"),
        ("synopsis", "doc"),
    ],
)
def test_legalxml_document_element(parsed, name, element):
    from lxml import etree

    root = etree.fromstring(render(parsed[name], "legalxml").encode())
    assert root.tag == f"{{{AKN_NS}}}akomaNtoso"
    assert root[0].tag == f"{{{AKN_NS}}}{element}"


def test_legalxml_bill_structure(parsed):
    from lxml import etree

    root = etree.fromstring(render(parsed["bill"], "legalxml").encode())
    ns = {"a": AKN_NS}
    secs = root.findall(".//a:body/a:section", ns)
    assert [s.findtext("a:num", namespaces=ns) for s in secs] == ["§ 1", "§ 2"]
    assert secs[1].findtext("a:heading", namespaces=ns) == "Inkrafttreten"
    eids = [e.get("eId") for e in root.iter() if e.get("eId")]
    assert len(eids) == len(set(eids)), "eIds must be unique"
    assert root.find(".//a:docNumber", ns).text == "19/1234"


def test_legalxml_debate_speeches(parsed):
    from lxml import etree

    root = etree.fromstring(render(parsed["protocol"], "legalxml").encode())
    ns = {"a": AKN_NS}
    speeches = root.findall(".//a:speech", ns)
    assert len(speeches) == 5
    persons = {p.get("eId") for p in root.findall(".//a:TLCPerson", ns)}
    assert all(s.get("by").lstrip("#") in persons for s in speeches)


def test_legalxml_embeds_fields(parsed):
    from lxml import etree

    root = etree.fromstring(render(parsed["letter"], "legalxml").encode())
    data = root.find(".//{urn:pazufa-parser:1.0}data")
    payload = json.loads(data.text)
    assert payload["fields"]["letter"]["salutation"] == "Sehr geehrte Frau Muster,"


def test_legalxml_strips_invalid_xml_chars(parsed):
    from lxml import etree

    d = parsed["two_column"]
    b = d.body_blocks[0]
    old = b.text
    b.text = old + "\x0b\x1f"
    try:
        etree.fromstring(render(d, "legalxml").encode())
    finally:
        b.text = old
