"""The public PdfDocument built at the end of the pipeline."""

import json
import tomllib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import NO_OCR
from pazufa_pdf_parser import (
    Block,
    BlockKind,
    Issue,
    Metadata,
    Page,
    PageReport,
    PageSource,
    PazufaError,
    PdfDocument,
    Report,
    SchemaVersionError,
    Severity,
    __version__,
    parse,
)
from pazufa_pdf_parser._pipeline.api import pdf_date
from pdfgen import make_pdf, paragraph

ALL_DOCS = ["letter", "bill", "email", "protocol", "judgment", "contract", "synopsis", "two_column"]
CET = timezone(timedelta(hours=1))


@pytest.mark.parametrize("name", ALL_DOCS)
def test_page_texts_add_up_to_the_document_text(parsed, name):
    d = parsed[name]
    assert "\n\n".join(t for p in d.pages if (t := p.text())) == d.text()
    assert all(d.text(pages=[p.number]) == p.text() for p in d.pages)
    assert d.text(pages=[]) == d.text(pages=[99]) == ""


def test_furniture_is_kept_apart_from_the_text(parsed):
    first, second = parsed["letter"].pages
    assert "- 2 -" not in parsed["letter"].text()
    assert second.furniture_text == "- 2 -\nVerband der Testbetriebe e.V. · Registergericht München VR 12345"
    assert second.label == "2" and first.label is None  # letters number pages from the second on
    email = parsed["email"].pages[0]
    assert email.furniture_text == "" and email.label is None


def _page(*blocks: tuple[BlockKind, str]) -> Page:
    return Page(
        number=1,
        source=PageSource.TEXT,
        blocks=tuple(Block(page=1, kind=k, text=t, bbox=(0.0, 0.0, 1.0, 1.0)) for k, t in blocks),
    )


@pytest.mark.parametrize(
    "page,label",
    [
        (_page((BlockKind.PAGE_NUMBER, "Seite 3 von 10")), "3"),
        (_page((BlockKind.PAGE_NUMBER, "3/10")), "3"),
        (_page((BlockKind.PAGE_NUMBER, "II")), "II"),
        (_page((BlockKind.PARAGRAPH, "7"), (BlockKind.HEADER, "Drucksache 19/1234")), None),
        (_page(), None),
    ],
    ids=["seite-von", "slash", "roman", "numbers-outside-page-number", "empty"],
)
def test_label(page, label):
    assert page.label == label


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


# one of everything, with optional fields at their defaults
DOC = PdfDocument(
    sha256="0" * 64,
    metadata=Metadata(title="T", author=None, created=datetime(2026, 1, 2, tzinfo=CET), modified=None, page_count=1),
    pages=(
        Page(
            number=1,
            source=PageSource.TEXT,
            blocks=(Block(page=1, kind=BlockKind.PARAGRAPH, text="Text", bbox=(1.0, 2.0, 3.0, 4.0)),),
        ),
    ),
    report=Report(
        parser_version="0.0.0",
        pages=(PageReport(number=1, ocr_reason="text layer", ocr_confidence=None),),
        issues=(Issue(severity=Severity.WARNING, step="ocr", message="m"),),
    ),
)


def _edited(edit) -> str:
    data = json.loads(DOC.to_json())
    edit(data)
    return json.dumps(data)


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: None,
        lambda d: d.update(future=1),
        lambda d: d["metadata"].update(subject="x"),
        lambda d: d["pages"][0].update(rotation=90),
        lambda d: d["pages"][0]["blocks"][0].update(confidence=0.9),
        lambda d: d["report"]["pages"][0].update(engine="tesseract"),
        lambda d: d["report"]["issues"][0].update(code="ocr_skipped"),
        lambda d: d["pages"][0]["blocks"][0].pop("level"),
        lambda d: d["report"]["issues"][0].pop("page"),
    ],
    ids=[
        "as-written",
        "new-top-key",
        "new-metadata-key",
        "new-page-key",
        "new-block-key",
        "new-page-report-key",
        "new-issue-key",
        "older-without-block-level",
        "older-without-issue-page",
    ],
)
def test_from_json_reads_newer_and_older_writers(edit):
    # new keys come from a newer parser sharing the cache, missing optional ones from an older one
    loaded = PdfDocument.from_json(_edited(edit))
    assert loaded == DOC
    assert loaded.report.issues[0].severity is Severity.WARNING and loaded.pages[0].source is PageSource.TEXT


@pytest.mark.parametrize(
    "s,error,match",
    [
        ('{"schema_version": 2}', SchemaVersionError, "reads up to 1"),
        ('{"schema_version": "1"}', PazufaError, "schema_version '1'"),
        ('{"schema_version": true}', PazufaError, "schema_version True"),
        ('{"schema_version": 0}', PazufaError, "schema_version 0"),
        ("", PazufaError, "not a PdfDocument"),
        ("[]", PazufaError, "not a PdfDocument"),
        ("null", PazufaError, "not a PdfDocument"),
        ('{"schema_version": 1}', PazufaError, "not a PdfDocument"),
        (_edited(lambda d: d.pop("sha256")), PazufaError, "sha256"),
        (_edited(lambda d: d["pages"][0]["blocks"][0].pop("text")), PazufaError, "text"),
        (_edited(lambda d: d.update(pages=[1])), PazufaError, "not a PdfDocument"),
        (_edited(lambda d: d["pages"][0]["blocks"][0].update(kind="label")), PazufaError, "'label'"),
        (_edited(lambda d: d["report"]["issues"][0].update(severity="fatal")), PazufaError, "'fatal'"),
        (_edited(lambda d: d["metadata"].update(created="gestern")), PazufaError, "gestern"),
        ("[" * 100_000, PazufaError, "not a PdfDocument"),
    ],
    ids=[
        "newer-schema",
        "version-as-text",
        "version-bool",
        "version-zero",
        "empty",
        "not-an-object",
        "null",
        "missing-fields",
        "missing-required-top-key",
        "missing-required-block-key",
        "page-not-an-object",
        "unknown-block-kind",
        "unknown-severity",
        "bad-date",
        "deeply-nested",
    ],
)
def test_from_json_rejects(s, error, match):
    with pytest.raises(error, match=match) as e:
        PdfDocument.from_json(s)
    # only a newer schema is SchemaVersionError: callers re-parse it instead of treating the cache as corrupt
    assert (e.type is SchemaVersionError) == (error is SchemaVersionError)
