"""The public PdfDocument built at the end of the pipeline."""

import tomllib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import NO_OCR
from pazufa_pdf_parser import PazufaError, PdfDocument, __version__, parse
from pazufa_pdf_parser._pipeline.api import pdf_date
from pdfgen import make_pdf, paragraph

ALL_DOCS = ["letter", "bill", "email", "protocol", "judgment", "contract", "synopsis", "two_column"]
CET = timezone(timedelta(hours=1))


@pytest.mark.parametrize("name", ALL_DOCS)
def test_page_texts_add_up_to_the_document_text(parsed, name):
    d = parsed[name]
    assert "\n\n".join(t for p in d.pages if (t := p.text)) == d.text()
    assert all(d.text(pages=[p.number]) == p.text for p in d.pages)
    assert d.text(pages=[]) == d.text(pages=[99]) == ""


def test_text_leaves_out_furniture(parsed):
    d = parsed["letter"]
    assert any(b.kind.value == "page_number" and b.text == "- 2 -" for b in d.blocks)
    assert "- 2 -" not in d.text()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("D:20211207123456+01'00'", datetime(2021, 12, 7, 12, 34, 56, tzinfo=CET)),
        ("D:20211207123456-05'30", datetime(2021, 12, 7, 12, 34, 56, tzinfo=timezone(-timedelta(hours=5, minutes=30)))),
        ("D:20211207123456Z", datetime(2021, 12, 7, 12, 34, 56, tzinfo=timezone.utc)),
        ("D:20260420045452", datetime(2026, 4, 20, 4, 54, 52)),
        ("D:2021", datetime(2021, 1, 1)),
        ("20211207", datetime(2021, 12, 7)),
        ("D:20211307", None),
        ("D:20211207123456+25'00'", None),
        ("gestern", None),
        ("", None),
        (None, None),
    ],
    ids=[
        "zone",
        "negative-zone",
        "utc",
        "no-zone",
        "year-only",
        "no-prefix",
        "month-13",
        "zone-25h",
        "text",
        "empty",
        "missing",
    ],
)
def test_pdf_date(value, expected):
    assert pdf_date(value) == expected


def test_metadata(bill_pdf):
    d = parse(bill_pdf, replace(NO_OCR, first_page=2, last_page=2))
    assert d.metadata.page_count == 2 and len(d.pages) == 1
    assert d.metadata.title is None and d.metadata.created is None  # pdfgen writes no info by default
    assert parse(make_pdf([paragraph(70, 100, ["Text"])], title="Testbrief"), NO_OCR).metadata.title == "Testbrief"


def test_report(parsed):
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    report = parsed["letter"].report
    assert report.parser_version == __version__ == pyproject["project"]["version"]
    assert [(p.number, p.ocr_reason, p.ocr_confidence) for p in report.pages] == [
        (1, "ocr disabled", None),
        (2, "ocr disabled", None),
    ]
    assert report.issues == ()


@pytest.mark.parametrize(
    "s,match",
    [
        ('{"schema_version": 2}', "schema_version 2"),
        ("", "not a PdfDocument"),
        ("[]", "not a PdfDocument"),
        ('{"schema_version": 1}', "not a PdfDocument"),
        ("[" * 100_000, "not a PdfDocument"),
    ],
    ids=["other-schema", "empty", "not-an-object", "missing-fields", "deeply-nested"],
)
def test_from_json_rejects(s, match):
    with pytest.raises(PazufaError, match=match):
        PdfDocument.from_json(s)
