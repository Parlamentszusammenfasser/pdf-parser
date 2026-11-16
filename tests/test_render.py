import json
from html.parser import HTMLParser

import pytest

from pazufa_pdf_parser import UnknownFormatError, available_formats, register_renderer, render

ALL_DOCS = ["letter", "bill", "email", "protocol", "judgment", "contract", "synopsis", "two_column"]


def test_formats_registered():
    assert {"raw", "txt", "html", "json"} <= set(available_formats())


def test_unknown_format(parsed):
    with pytest.raises(UnknownFormatError):
        render(parsed["letter"], "pdf")


def test_custom_renderer(parsed):
    register_renderer("upper", lambda d: render(d, "txt").upper(), "up.txt")
    try:
        assert "SEHR GEEHRTE" in render(parsed["letter"], "upper")
    finally:
        from pazufa_pdf_parser.render import _REGISTRY

        _REGISTRY.pop("upper", None)


@pytest.mark.parametrize("name", ALL_DOCS)
def test_raw_contains_the_txt(parsed, name):
    assert set(render(parsed[name], "txt").split()) <= set(render(parsed[name], "raw").split())


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


def test_html_is_body_in_reading_order(parsed):
    html = render(parsed["two_column"], "html")
    assert html.index("vor der rechten Spalte gelesen werden muss.") < html.index("Völlig anderer Inhalt")
    assert "Registergericht" not in render(parsed["letter"], "html")  # page footer left out


def test_html_escapes(parsed):
    html = render(parsed["email"], "html")
    assert "&lt;t.schmid@example.org&gt;" in html
