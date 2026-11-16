"""The public API: exactly the names in __all__, typed for strict consumers."""

from pathlib import Path

import mypy.api
import pytest

import pazufa_pdf_parser
from pazufa_pdf_parser import OcrMode, ParseOptions


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
            "PazufaError",
            "PdfOpenError",
            "OcrUnavailableError",
        ]
    )


def test_strict_consumer_type_checks():
    # without py.typed mypy sees the package as untyped and this fails
    consumer = Path(__file__).with_name("public_api_consumer.py")
    out, err, status = mypy.api.run(["--strict", "--config-file", "", str(consumer)])
    assert status == 0, out + err


def test_ocr_mode_from_string():
    # ParseOptions(ocr="never") used to be compared by identity and silently ran as "auto"
    assert ParseOptions(ocr="never").ocr is OcrMode.NEVER  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sometimes"):
        ParseOptions(ocr="sometimes")  # type: ignore[arg-type]
