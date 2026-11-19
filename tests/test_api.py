"""The public API: exactly the names in __all__, typed for strict consumers."""

import pickle
import re
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest

import pazufa_pdf_parser
from pazufa_pdf_parser import (
    Block,
    Issue,
    Metadata,
    Ocr,
    OcrMode,
    Page,
    PageReport,
    ParseOptions,
    PdfDocument,
    PdfOpenError,
    Report,
    SchemaVersionError,
    Severity,
    StepError,
)

# callers build and read these by field name: adding a field (with a default) extends a list here,
# renaming or removing one breaks callers
PUBLIC_FIELDS = {
    Block: ["page", "kind", "text", "bbox", "level"],
    Page: ["number", "source", "blocks", "printed_page"],
    Metadata: ["title", "author", "created", "modified", "page_count"],
    PageReport: ["number", "ocr_reason", "ocr_confidence"],
    Report: ["parser_version", "pages", "issues"],
    Issue: ["severity", "step", "message", "page"],
    PdfDocument: ["sha256", "metadata", "pages", "report"],
    ParseOptions: [
        "ocr",
        "ocr_engine",
        "strict",
        "password",
        "min_text_chars",
        "max_garbage_ratio",
        "min_word_confidence",
        "first_page",
        "last_page",
        "max_ocr_pages",
    ],
    Ocr: ["languages", "dpi", "max_parallel", "timeout", "tesseract_cmd", "detect_orientation"],
}


def test_all_is_the_public_api():
    assert sorted(pazufa_pdf_parser.__all__) == sorted(
        [
            "parse",
            "ParseOptions",
            "OcrMode",
            "Ocr",
            "PdfDocument",
            "Page",
            "Block",
            "BlockKind",
            "PageSource",
            "Metadata",
            "Report",
            "PageReport",
            "Issue",
            "Severity",
            "render",
            "Format",
            "PazufaError",
            "PdfOpenError",
            "OcrUnavailableError",
            "StepError",
            "UnknownFormatError",
            "SchemaVersionError",
            "Source",
        ]
    )


CONSUMER = str(Path(__file__).with_name("public_api_consumer.py"))
TYPO = "from pazufa_pdf_parser import PdfDocument, render\ndef f(d: PdfDocument) -> str:\n    return render(d, 'htm')"


@pytest.mark.parametrize(
    "target,error",
    [([CONSUMER], None), (["-c", TYPO], "Literal['htm']")],
    ids=["consumer", "render-format-typo"],
)
def test_strict_consumer_type_checks(target, error):
    pytest.importorskip("mypy")
    # without py.typed mypy sees the package as untyped: the consumer fails and the typo goes unnoticed
    cmd = [sys.executable, "-m", "mypy", "--strict", "--config-file", "", *target]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if error is None:
        assert r.returncode == 0, r.stdout + r.stderr
    else:
        assert r.returncode == 1 and error in r.stdout, r.stdout + r.stderr


# documented on Issue.step; callers filter on them, e.g. "ocr" to alert on scans left without OCR
ISSUE_STEPS = {"extract", "ocr", "layout", "furniture", "sanitize", "flow"}


def test_issue_steps_are_the_documented_ones():
    from pazufa_pdf_parser._pipeline.pipeline import Pipeline

    pipeline = Path(pazufa_pdf_parser.__file__).parent / "_pipeline"
    named = {m for f in pipeline.rglob("*.py") for m in re.findall(r'\.issue\(\s*[^,]+,\s*"(\w+)"', f.read_text())}
    assert named == {"extract", "ocr"}  # the scan works; a new name here must be added to ISSUE_STEPS and the docs
    assert set(Pipeline().names()) | named == ISSUE_STEPS


@pytest.mark.parametrize("cls", PUBLIC_FIELDS, ids=lambda c: c.__name__)
def test_public_types_are_frozen_and_keyword_only(cls):
    assert [f.name for f in fields(cls)] == PUBLIC_FIELDS[cls]
    # keyword-only, so a new field can go anywhere without shifting callers' arguments
    with pytest.raises(TypeError, match="positional argument but"):
        cls(*[None] * len(fields(cls)))
    assert cls.__dataclass_params__.frozen  # a shared Ocr or a cached result must not change under its users


def test_severity_orders_by_severity():
    # StrEnum compares alphabetically, where "error" < "info" and `>= WARNING` drops errors
    assert sorted([Severity.ERROR, Severity.INFO, Severity.WARNING]) == [
        Severity.INFO,
        Severity.WARNING,
        Severity.ERROR,
    ]
    assert Severity.ERROR > Severity.WARNING >= Severity.WARNING > Severity.INFO
    assert Severity.ERROR >= "warning" and "info" < Severity.WARNING  # plain strings, e.g. from config
    assert Severity.ERROR == "error" and max([Severity.INFO, Severity.ERROR]) is Severity.ERROR
    with pytest.raises(ValueError, match="fatal"):
        Severity.ERROR > "fatal"  # noqa: B015
    with pytest.raises(TypeError):
        Severity.ERROR > 1  # noqa: B015


@pytest.mark.parametrize(
    "obj",
    [
        StepError("ocr", RuntimeError("tesseract failed")),
        PdfOpenError("not a PDF"),
        SchemaVersionError("schema_version 2"),
        ParseOptions(ocr=OcrMode.NEVER, max_ocr_pages=3, ocr_engine=Ocr(dpi=150, max_parallel=1)),
    ],
    ids=["step-error", "open-error", "schema-error", "options"],
)
def test_survives_pickling(obj):
    # options go to and errors come back from process pools; an unpicklable error breaks the whole pool
    clone = pickle.loads(pickle.dumps(obj))  # noqa: S301
    assert type(clone) is type(obj) and repr(clone) == repr(obj)
    assert getattr(clone, "step", None) == getattr(obj, "step", None)
